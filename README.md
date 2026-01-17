# Fundamentals Analysis

A Python-based stock research automation bot for fundamental analysis. This tool performs screening, data collection, ratio analysis, and generates reports for stock investment research.

**⚠️ Disclaimer: This tool is for personal learning and investment research only. It does not provide financial advice.**

## Features

- **Stock Screener**: Filter stocks based on financial criteria (P/E ratio, market cap, ROE, etc.)
- **Financial Data Fetching**: Automatically retrieve income statements, balance sheets, and key metrics
- **Ratio Calculations**: Calculate key financial ratios (Current Ratio, Debt-to-Equity, ROE, Revenue Growth)
- **CLI Interface**: Easy-to-use command-line interface for screening operations
- **CSV/JSON Export**: Export screening results to CSV or JSON for further analysis
- **Local Cache**: Built-in cache to reduce API calls and speed up re-runs
- **Ticker Files**: Load tickers from a text/CSV file

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd fundamentals_analysis
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Quick Start

### Basic Usage

Screen specific tickers with default criteria:
```bash
python -m src screen --tickers AAPL,MSFT,GOOGL
```

Screen with custom output file:
```bash
python -m src screen --tickers AAPL,MSFT --output outputs/my_results.csv
```

Screen using a ticker file and JSON output:
```bash
python -m src screen --tickers-file data/tickers.txt --format json --output outputs/results.json
```

Use custom configuration file:
```bash
python -m src screen --config config/config.yaml --tickers AAPL,MSFT
```

Use inline criteria:
```bash
python -m src screen --tickers AAPL --criteria "pe_max=20,market_cap_min=1000000000,roe_min=0.15"
```

Filter to only show passing stocks:
```bash
python -m src screen --tickers AAPL,MSFT,GOOGL --filter-passed
```

Print results to stdout:
```bash
python -m src screen --tickers AAPL,MSFT --show
```

Disable cache or adjust cache TTL:
```bash
python -m src screen --tickers AAPL --no-cache
python -m src screen --tickers AAPL --cache-ttl-hours 6
```

## Configuration

Edit `config/config.yaml` to customize screening criteria:

```yaml
screener:
  criteria:
    market_cap_min: 1000000000  # $1B minimum
    pe_max: 25                   # Maximum P/E ratio
    current_ratio_min: 1.5       # Minimum current ratio
    debt_to_equity_max: 1.0      # Maximum debt-to-equity ratio
    revenue_growth_min: 0.05      # 5% minimum revenue growth
    positive_earnings: true       # Must have positive net income
    roe_min: 0.15                # 15% minimum ROE
  default_tickers:
    - AAPL
    - MSFT
    - GOOGL
```

## Understanding the Metrics

### Current Ratio
- **Formula**: Current Assets / Current Liabilities
- **What it measures**: Short-term liquidity - ability to pay short-term obligations
- **Interpretation**: Higher is better. Values above 1.0 indicate company can cover current liabilities. Values between 1.5-3.0 are generally considered healthy.

### Debt-to-Equity Ratio
- **Formula**: Total Debt / Total Stockholders Equity
- **What it measures**: Financial leverage - how much debt vs equity company uses
- **Interpretation**: Lower is generally better (less risky). Values below 1.0 are conservative. Values above 2.0 indicate high leverage and higher risk.

### Return on Equity (ROE)
- **Formula**: Net Income / Shareholders Equity
- **What it measures**: How efficiently company uses equity to generate profit
- **Interpretation**: Higher is better. Above 15% is generally strong, below 10% may indicate issues. Shows management's ability to generate returns for shareholders.

### Revenue Growth
- **Formula**: (Current Revenue - Previous Revenue) / Previous Revenue
- **What it measures**: Year-over-year revenue growth rate
- **Interpretation**: Higher is better for growth companies. Positive growth indicates expansion. Negative growth may signal declining business.

### P/E Ratio (Price-to-Earnings)
- **Formula**: Market Price per Share / Earnings per Share
- **What it measures**: Price relative to earnings
- **Interpretation**: Lower is generally better for value investors, but growth stocks may have higher P/E ratios. Typical "reasonable" P/E is 15-25, but varies by industry.

## Project Structure

```
fundamentals_analysis/
├── README.md
├── requirements.txt
├── .gitignore
├── config/
│   └── config.yaml          # Configuration for screening criteria
├── src/
│   ├── __init__.py
│   ├── __main__.py          # Main entry point
│   ├── screener/
│   │   ├── __init__.py
│   │   ├── screener.py      # Main screener logic
│   │   └── criteria.py      # Screening criteria definitions
│   ├── data/
│   │   ├── __init__.py
│   │   └── fetcher.py       # yfinance data fetching utilities
│   └── utils/
│       ├── __init__.py
│       └── cli.py           # CLI interface
├── data/
│   └── .gitkeep            # Placeholder for data files
├── outputs/
│   └── .gitkeep            # Placeholder for CSV outputs
└── tests/
    ├── __init__.py
    └── test_screener.py    # Unit tests for screener
```

## Output Format

The screener generates a CSV file with the following columns:

- `ticker`: Stock symbol
- `company_name`: Company name
- `market_cap`: Market capitalization
- `pe_ratio`: P/E ratio
- `current_ratio`: Current ratio
- `debt_to_equity`: Debt-to-equity ratio
- `revenue_growth`: Revenue growth %
- `roe`: Return on Equity %
- `passed_criteria`: Number of criteria passed
- `total_criteria`: Total number of criteria
- `failed_criteria`: List of failed criteria
- `status`: PASS/FAIL

## Running Tests

Run the test suite:
```bash
python -m pytest tests/
```

Or run specific test file:
```bash
python -m pytest tests/test_screener.py
```

## Error Handling

The screener handles various error conditions:

- **Invalid ticker symbols**: Skipped with warning message
- **Missing financial data**: Skipped ticker, reason logged
- **API rate limits**: Automatic delays between requests
- **Network errors**: Retry logic (3 attempts with exponential backoff)

## Limitations

- Data is fetched from yfinance, which may have rate limits
- Some companies may have incomplete financial data
- Calculations are based on annual financial statements
- This is Week 1 MVP - more features coming in future phases

## Future Enhancements

Planned features for upcoming phases:

- **Week 2**: SEC EDGAR integration for 10-K filings, financial statement parsing, SQLite database
- **Week 3**: Advanced ratio calculations (CAGR, margins, efficiency ratios), DCF valuation model
- **Week 4**: PDF report generation with charts and explanations
- **Phase 2**: AI-powered SWOT analysis, web dashboard, backtesting
- **Phase 3**: Peer comparison, industry analysis, portfolio tracking

## Contributing

This is a personal learning project. Feel free to fork and adapt for your own use.

## License

See LICENSE file for details.

## Resources

- [yfinance Documentation](https://github.com/ranaroussi/yfinance)
- [SEC EDGAR Database](https://www.sec.gov/edgar/searchedgar/companysearch.html)
- Financial ratio explanations and benchmarks
