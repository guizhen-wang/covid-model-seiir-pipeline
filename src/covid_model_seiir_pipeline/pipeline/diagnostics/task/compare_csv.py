from pathlib import Path

import click
from loguru import logger
import pandas as pd

from covid_model_seiir_pipeline.lib import (
    cli_tools,
    static_vars,
)
from covid_model_seiir_pipeline.pipeline.diagnostics.specification import (
    DiagnosticsSpecification,
)
from covid_model_seiir_pipeline.pipeline.diagnostics import model


def run_compare_csv(diagnostics_version: str):
    """Make the cumulative death comparison file."""
    logger.info(f'Starting compare csv for version {diagnostics_version}')
    diagnostics_spec = DiagnosticsSpecification.from_path(
        Path(diagnostics_version) / static_vars.DIAGNOSTICS_SPECIFICATION_FILE
    )
    compare_csv_spec = diagnostics_spec.compare_csv

    # Plot version objects are specific to a version and scenario and
    # encapsulate all the data and metadata necessary to plot that particular
    # version/scenario combo.
    logger.info('Building plot versions')
    plot_versions = model.make_plot_versions(compare_csv_spec.comparators, model.COLOR_MAP)
    dates = [pd.Timestamp(date) for date in compare_csv_spec.dates]

    for plot_version in plot_versions:
        plot_data = plot_version.load_output_summaries('cumulative_deaths')
        plot_data = (
            plot_data
            .loc[plot_data.date.isin(dates)]
            .set_index(['location_id', 'date'])
            .unstack()
        )







@click.command()
@cli_tools.with_diagnostics_version
@cli_tools.add_verbose_and_with_debugger
def compare_csv(diagnostics_version: str,
                verbose: int, with_debugger: bool):
    """Produce cumulative deaths compare csv."""
    cli_tools.configure_logging_to_terminal(verbose)
    run = cli_tools.handle_exceptions(run_compare_csv, logger, with_debugger)
    run(diagnostics_version=diagnostics_version)


if __name__ == '__main__':
    compare_csv()
