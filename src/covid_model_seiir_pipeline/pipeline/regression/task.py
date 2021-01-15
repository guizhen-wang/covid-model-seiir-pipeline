from pathlib import Path

import click
import numpy as np
import pandas as pd

from covid_model_seiir_pipeline.lib import (
    cli_tools,
    math,
    static_vars,
)
from covid_model_seiir_pipeline.pipeline.regression.data import RegressionDataInterface
from covid_model_seiir_pipeline.pipeline.regression.specification import RegressionSpecification
from covid_model_seiir_pipeline.pipeline.regression import model


logger = cli_tools.task_performance_logger


def run_beta_regression(regression_version: str, draw_id: int) -> None:
    logger.info('Starting beta regression.', context='setup')
    # Build helper abstractions
    regression_spec_file = Path(regression_version) / static_vars.REGRESSION_SPECIFICATION_FILE
    regression_specification = RegressionSpecification.from_path(regression_spec_file)
    data_interface = RegressionDataInterface.from_specification(regression_specification)

    logger.info('Loading input data', context='read')
    location_ids = data_interface.load_location_ids()
    location_data = data_interface.load_all_location_data(location_ids=location_ids,
                                                          draw_id=draw_id)
    covariates = data_interface.load_covariates(regression_specification.covariates, location_ids)

    logger.info('Prepping ODE fit', context='transform')
    np.random.seed(draw_id)
    beta_fit_inputs = model.ODEProcessInput(
        df_dict=location_data,
        col_date=static_vars.INFECTION_COL_DICT['COL_DATE'],
        col_cases=static_vars.INFECTION_COL_DICT['COL_CASES'],
        col_pop=static_vars.INFECTION_COL_DICT['COL_POP'],
        col_loc_id=static_vars.INFECTION_COL_DICT['COL_LOC_ID'],
        col_lag_days=static_vars.INFECTION_COL_DICT['COL_ID_LAG'],
        col_observed=static_vars.INFECTION_COL_DICT['COL_OBS_DEATHS'],
        alpha=regression_specification.parameters.alpha,
        sigma=regression_specification.parameters.sigma,
        gamma1=regression_specification.parameters.gamma1,
        gamma2=regression_specification.parameters.gamma2,
        solver_dt=regression_specification.parameters.solver_dt,
        day_shift=regression_specification.parameters.day_shift,
    )
    ode_model = model.ODEProcess(beta_fit_inputs)
    logger.info('Running ODE fit', context='compute_ode')
    beta_fit = ode_model.process()
    beta_fit['date'] = pd.to_datetime(beta_fit['date'])

    logger.info('Prepping regression.', context='transform')
    mr_data = model.align_beta_with_covariates(covariates, beta_fit, list(regression_specification.covariates))
    regressor = model.build_regressor(regression_specification.covariates.values())
    logger.info('Fitting beta regression', context='compute_regression')
    coefficients = regressor.fit(mr_data, regression_specification.parameters.sequential_refit)
    log_beta_hat = math.compute_beta_hat(covariates, coefficients)
    beta_hat = np.exp(log_beta_hat).rename('beta_pred').reset_index()

    # Format and save data.
    logger.info('Prepping outputs', context='transform')
    data_df = pd.concat(location_data.values())
    data_df['date'] = pd.to_datetime(data_df['date'])
    regression_betas = beta_hat.merge(covariates, on=['location_id', 'date'])
    regression_betas = beta_fit.merge(regression_betas, on=['location_id', 'date'], how='left')
    merged = data_df.merge(regression_betas, on=['location_id', 'date'], how='outer').sort_values(['location_id', 'date'])
    merged = merged[(merged['obs_deaths'] == 1) | (merged['deaths_draw'] > 0)]
    data_df = merged[data_df.columns]
    regression_betas = merged[regression_betas.columns]
    # Save the parameters of alpha, sigma, gamma1, and gamma2 that were drawn
    draw_beta_params = ode_model.create_params_df()
    beta_start_end_dates = ode_model.create_start_end_date_df()

    logger.info('Writing outputs', context='write')
    data_interface.save_location_data(data_df, draw_id)
    data_interface.save_regression_betas(regression_betas, draw_id)
    data_interface.save_regression_coefficients(coefficients, draw_id)
    data_interface.save_beta_param_file(draw_beta_params, draw_id)
    data_interface.save_date_file(beta_start_end_dates, draw_id)

    logger.report()


@click.command()
@cli_tools.with_regression_version
@cli_tools.with_draw_id
@cli_tools.add_verbose_and_with_debugger
def beta_regression(regression_version: str, draw_id: int,
                    verbose: int, with_debugger: bool):
    cli_tools.configure_logging_to_terminal(verbose)

    run = cli_tools.handle_exceptions(run_beta_regression, logger, with_debugger)
    run(regression_version=regression_version,
        draw_id=draw_id)


if __name__ == '__main__':
    beta_regression()
