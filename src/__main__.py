"""
Main entry point for running the package as a module.

Allows running: python -m src screen --tickers AAPL,MSFT
"""

from .utils.cli import cli

if __name__ == '__main__':
    cli()

