from pathlib import Path

from covid_shared import cli_tools

from covid_model_seiir_pipeline import static_vars

from covid_model_seiir_pipeline.paths import ForecastPaths
from covid_model_seiir_pipeline.forecasting import ForecastSpecification
from covid_model_seiir_pipeline.forecasting.data import ForecastDataInterface
from covid_model_seiir_pipeline.ode_fit.specification import FitSpecification
from covid_model_seiir_pipeline.regression.specification import RegressionSpecification


def do_beta_forecast(app_metadata: cli_tools.Metadata,
                     forecast_specification: ForecastSpecification,
                     output_root: Path):
    regression_specification: RegressionSpecification = RegressionSpecification.from_path(
        Path(forecast_specification.data.regression_version) /
        static_vars.REGRESSION_SPECIFICATION_FILE
    )
    ode_fit_spec: FitSpecification = FitSpecification.from_path(
        Path(regression_specification.data.ode_fit_version) /
        static_vars.FIT_SPECIFICATION_FILE
    )

    for scenario in forecast_specification.scenarios.keys():
        scenario_root = output_root / scenario

        # init high level objects
        forecast_paths = ForecastPaths(scenario_root, read_only=False)
        data_interface = ForecastDataInterface(
            forecast_root=scenario_root,
            regression_root=Path(regression_specification.data.output_root),
            ode_fit_root=Path(ode_fit_spec.data.output_root),
            location_file=(Path('/ihme/covid-19/seir-pipeline-outputs/metadata-inputs') /
                           f'location_metadata_{ode_fit_spec.data.location_set_version_id}.csv'
                           )
        )

        # build directory structure
        location_ids = data_interface.load_location_ids()
        forecast_paths.make_dirs(location_ids)
