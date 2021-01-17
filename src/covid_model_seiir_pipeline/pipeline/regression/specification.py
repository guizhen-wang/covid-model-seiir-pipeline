from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Tuple

from covid_model_seiir_pipeline.lib import (
    utilities,
    workflow,
)


class __RegressionJobs(NamedTuple):
    regression: str = 'beta_regression'


REGRESSION_JOBS = __RegressionJobs()


class RegressionTaskSpecification(workflow.TaskSpecification):
    """Specification of execution parameters for regression tasks."""
    default_max_runtime_seconds = 3000
    default_m_mem_free = '2G'
    default_num_cores = 1


class RegressionWorkflowSpecification(workflow.WorkflowSpecification):
    """Specification of execution parameters for regression workflows."""
    tasks = {
        REGRESSION_JOBS.regression: RegressionTaskSpecification,
    }


@dataclass
class RegressionData:
    """Specifies the inputs and outputs for a regression"""
    covariate_version: str = field(default='best')
    infection_version: str = field(default='best')
    coefficient_version: str = field(default='')
    location_set_version_id: int = field(default=0)
    location_set_file: str = field(default='')
    output_root: str = field(default='')

    def to_dict(self) -> Dict:
        """Converts to a dict, coercing list-like items to lists."""
        return utilities.asdict(self)


@dataclass
class RegressionParameters:
    """Specifies the parameters of the beta fit and regression."""
    n_draws: int = field(default=1000)

    day_shift: Tuple[int, int] = field(default=(0, 8))

    alpha: Tuple[float, float] = field(default=(0.9, 1.0))
    sigma: Tuple[float, float] = field(default=(0.2, 1/3))
    gamma1: Tuple[float, float] = field(default=(0.5, 0.5))
    gamma2: Tuple[float, float] = field(default=(1/3, 1.0))
    solver_dt: float = field(default=0.1)
    sequential_refit: bool = field(default=False)

    def to_dict(self) -> Dict:
        """Converts to a dict, coercing list-like items to lists."""
        return utilities.asdict(self)


@dataclass
class CovariateSpecification:
    """Regression specification for a covariate."""

    # model params
    name: str = field(default='covariate')
    order: int = field(default=0)
    use_re: bool = field(default=False)
    gprior: Tuple[float, float] = field(default=(0., 1000.))
    bounds: Tuple[float, float] = field(default=(-1000., 1000.))
    re_var: float = field(default=1.)
    draws: bool = field(default=False)

    def to_dict(self) -> Dict:
        """Converts to a dict, coercing list-like items to lists.

        Drops the name parameter as it's used as a key in the specification.

        """
        return {k: v for k, v in utilities.asdict(self).items() if k != 'name'}


class RegressionSpecification(utilities.Specification):
    """Specification for a regression run."""

    def __init__(self,
                 data: RegressionData,
                 workflow: RegressionWorkflowSpecification,
                 regression_parameters: RegressionParameters,
                 covariates: List[CovariateSpecification]):
        self._data = data
        self._workflow = workflow
        self._regression_parameters = regression_parameters
        self._covariates = {c.name: c for c in covariates}

    @classmethod
    def parse_spec_dict(cls, regression_spec_dict: Dict) -> Tuple:
        """Constructs a regression specification from a dictionary."""
        sub_specs = {
            'data': RegressionData,
            'workflow': RegressionWorkflowSpecification,
            'regression_parameters': RegressionParameters,
        }
        sub_specs = {key: spec_class(**regression_spec_dict.get(key, {})) for key, spec_class in sub_specs.items()}

        # covariates
        cov_dicts = regression_spec_dict.get('covariates', {})
        covariates = []
        for name, cov_spec in cov_dicts.items():
            covariates.append(CovariateSpecification(name, **cov_spec))
        if not covariates:  # Assume we're generating for a template
            covariates.append(CovariateSpecification())
        sub_specs['covariates'] = covariates

        return tuple(sub_specs.values())

    @property
    def data(self) -> RegressionData:
        """The data specification for the regression."""
        return self._data

    @property
    def workflow(self) -> RegressionWorkflowSpecification:
        """The workflow specification for the regression."""
        return self._workflow

    @property
    def regression_parameters(self) -> RegressionParameters:
        """The parametrization of the regression."""
        return self._regression_parameters

    @property
    def covariates(self) -> Dict[str, CovariateSpecification]:
        """The covariates for the regression."""
        return self._covariates

    def to_dict(self) -> Dict:
        """Converts the specification to a dict."""
        spec = {
            'data': self.data.to_dict(),
            'workflow': self.workflow.to_dict(),
            'regression_parameters': self.regression_parameters.to_dict(),
            'covariates': {k: v.to_dict() for k, v in self._covariates.items()},
        }
        return spec

