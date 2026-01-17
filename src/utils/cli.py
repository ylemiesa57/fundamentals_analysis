"""
Command-line interface for the stock screener.

Provides CLI commands for screening stocks and generating reports.
"""

import logging
import sys
from pathlib import Path
from typing import Optional, List
import click
import pandas as pd

from ..screener.screener import StockScreener
from ..data.fetcher import DataFetcher
from ..screener.criteria import load_criteria_from_config, parse_inline_criteria

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """Stock Fundamentals Analysis CLI."""
    pass


@cli.command()
@click.option('--host', default='127.0.0.1', show_default=True, help='Host to bind the web app')
@click.option('--port', default=5000, show_default=True, help='Port to bind the web app')
@click.option('--debug', is_flag=True, help='Run web app in debug mode')
def web(host: str, port: int, debug: bool):
    """Run the Thesis Lab web UI."""
    from ..web.app import run as run_web
    run_web(host=host, port=port, debug=debug)


@cli.command()
@click.option(
    '--tickers',
    '-t',
    help='Comma-separated list of ticker symbols (e.g., AAPL,MSFT,GOOGL)'
)
@click.option(
    '--tickers-file',
    type=click.Path(exists=True),
    help='Path to a text/CSV file with tickers (one per line or comma-separated)'
)
@click.option(
    '--config',
    '-c',
    type=click.Path(exists=True),
    help='Path to YAML configuration file'
)
@click.option(
    '--output',
    '-o',
    default='outputs/screener_results.csv',
    help='Output CSV file path (default: outputs/screener_results.csv)'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['csv', 'json'], case_sensitive=False),
    default='csv',
    help='Output format: csv or json (default: csv)'
)
@click.option(
    '--criteria',
    help='Inline criteria string (e.g., "pe_max=25,market_cap_min=1000000000")'
)
@click.option(
    '--filter-passed',
    is_flag=True,
    help='Only output stocks that passed all criteria'
)
@click.option(
    '--show',
    is_flag=True,
    help='Print results to stdout in a table format'
)
@click.option(
    '--no-cache',
    is_flag=True,
    help='Disable local cache for fetched data'
)
@click.option(
    '--cache-ttl-hours',
    type=float,
    default=24.0,
    show_default=True,
    help='Cache freshness window in hours'
)
def screen(
    tickers: Optional[str],
    tickers_file: Optional[str],
    config: Optional[str],
    output: str,
    output_format: str,
    criteria: Optional[str],
    filter_passed: bool,
    show: bool,
    no_cache: bool,
    cache_ttl_hours: float,
):
    """
    Screen stocks against financial criteria.
    
    Examples:
    
    \b
    # Screen specific tickers with default config
    python -m src.utils.cli screen --tickers AAPL,MSFT,GOOGL
    
    \b
    # Use custom config file
    python -m src.utils.cli screen --config config/my_config.yaml --tickers AAPL,MSFT
    
    \b
    # Use inline criteria
    python -m src.utils.cli screen --tickers AAPL --criteria "pe_max=20,roe_min=0.15"
    
    \b
    # Only show passing stocks
    python -m src.utils.cli screen --tickers AAPL,MSFT --filter-passed
    """
    # Determine tickers to screen
    ticker_list: List[str] = []
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(',') if t.strip()]
    elif tickers_file:
        ticker_list = _load_tickers_from_file(Path(tickers_file))
    elif config:
        # Try to load default tickers from config
        import yaml
        try:
            with open(config, 'r') as f:
                config_data = yaml.safe_load(f)
                screener_config = config_data.get('screener', {})
                ticker_list = screener_config.get('default_tickers', [])
        except Exception as e:
            logger.error(f"Error loading default tickers from config: {str(e)}")
            click.echo("Error: Could not load default tickers from config. Please specify --tickers.", err=True)
            sys.exit(1)
    else:
        click.echo("Error: Must specify --tickers, --tickers-file, or --config", err=True)
        sys.exit(1)
    
    if not ticker_list:
        click.echo("Error: No tickers to screen", err=True)
        sys.exit(1)
    
    # Load criteria configuration
    criteria_config = {}
    if criteria:
        # Use inline criteria
        criteria_config = parse_inline_criteria(criteria)
        click.echo(f"Using inline criteria: {criteria_config}")
    elif config:
        # Load from config file
        criteria_config = load_criteria_from_config(config)
        click.echo(f"Loaded criteria from {config}")
    else:
        # Use default config
        criteria_config = load_criteria_from_config()
        click.echo("Using default criteria from config/config.yaml")
    
    if not criteria_config:
        click.echo("Warning: No criteria specified. All stocks will pass.", err=True)
    
    # Initialize screener
    try:
        fetcher = DataFetcher(
            cache_ttl_hours=cache_ttl_hours,
            use_cache=not no_cache,
        )
        screener = StockScreener(criteria_config, fetcher=fetcher)
    except Exception as e:
        click.echo(f"Error initializing screener: {str(e)}", err=True)
        sys.exit(1)
    
    # Run screening
    click.echo(f"\nScreening {len(ticker_list)} ticker(s): {', '.join(ticker_list)}")
    click.echo(f"Criteria: {len(screener.criteria_functions)} criteria configured\n")
    
    try:
        results_df = screener.screen_list(ticker_list)
    except Exception as e:
        click.echo(f"Error during screening: {str(e)}", err=True)
        sys.exit(1)
    
    # Filter if requested
    if filter_passed:
        results_df = screener.filter_by_criteria(results_df)
        click.echo(f"Filtered to {len(results_df)} passing stocks\n")
    
    # Ensure output directory exists
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save to CSV/JSON
    try:
        if output_format.lower() == 'json':
            output_path.write_text(results_df.to_json(orient='records', indent=2))
        else:
            results_df.to_csv(output_path, index=False)
        click.echo(f"Results saved to {output_path}")
    except Exception as e:
        click.echo(f"Error saving results: {str(e)}", err=True)
        sys.exit(1)
    
    # Display summary
    click.echo("\n" + "="*60)
    click.echo("SCREENING SUMMARY")
    click.echo("="*60)
    
    if show and len(results_df) > 0:
        click.echo("\nResults preview:")
        click.echo(results_df.to_string(index=False))
        click.echo("")

    if len(results_df) > 0:
        passed = len(results_df[results_df['status'] == 'PASS']) if 'status' in results_df.columns else 0
        failed = len(results_df) - passed
        
        click.echo(f"Total screened: {len(results_df)}")
        click.echo(f"Passed: {passed}")
        click.echo(f"Failed: {failed}")
        
        if passed > 0:
            click.echo("\nPassing stocks:")
            passing = results_df[results_df['status'] == 'PASS'] if 'status' in results_df.columns else pd.DataFrame()
            for _, row in passing.iterrows():
                click.echo(f"  {row['ticker']}: {row.get('company_name', 'N/A')}")
    else:
        click.echo("No results to display")
    
    click.echo("="*60)


if __name__ == '__main__':
    cli()


def _load_tickers_from_file(path: Path) -> List[str]:
    """Load tickers from a file (comma or newline separated)."""
    content = path.read_text()
    tickers: List[str] = []
    for raw_line in content.splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',') if p.strip()]
        tickers.extend(parts)
    # Allow a single-line, comma-separated file without newlines
    if not tickers and content.strip():
        tickers = [t.strip() for t in content.split(',') if t.strip()]
    return [t.upper() for t in tickers]
