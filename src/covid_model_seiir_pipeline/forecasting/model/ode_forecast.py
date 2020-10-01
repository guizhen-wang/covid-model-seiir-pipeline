from dataclasses import dataclass, asdict
from typing import Union

import numpy as np
from odeopt.ode import RK4
from odeopt.ode import ODESys
import pandas as pd

from covid_model_seiir_pipeline.math import compute_beta_hat


def forecast_beta(covariates, coefficients, beta_shift_parameters):
    log_beta_hat = compute_beta_hat(covariates, coefficients)
    beta_hat = np.exp(log_beta_hat).rename('beta_pred').reset_index()

    # Rescale the predictions of beta based on the residuals from the
    # regression.
    betas = _beta_shift(beta_hat, beta_shift_parameters).set_index('location_id')
    return betas


def run_normal_ode_model_by_location(initial_condition, beta_params, betas, thetas, location_ids, solver, ode_system):
    forecasts = []
    for location_id in location_ids:
        init_cond = initial_condition.loc[location_id].values
        total_population = init_cond.sum()

        model_specs = _SeiirModelSpecs(
            alpha=beta_params['alpha'],
            sigma=beta_params['sigma'],
            gamma1=beta_params['gamma1'],
            gamma2=beta_params['gamma2'],
            N=total_population,
        )
        ode_runner = _ODERunner(solver, ode_system, model_specs)

        loc_betas = betas.loc[location_id].sort_values('date')
        loc_days = loc_betas['date']
        loc_times = np.array((loc_days - loc_days.min()).dt.days)
        loc_betas = loc_betas['beta_pred'].values
        loc_thetas = np.repeat(thetas.get(location_id, default=0), loc_betas.size)

        forecasted_components = ode_runner.get_solution(init_cond, loc_times, loc_betas, loc_thetas)
        forecasted_components['date'] = loc_days.values
        forecasted_components['location_id'] = location_id
        forecasts.append(forecasted_components)
    forecasts = pd.concat(forecasts)
    return forecasts


class _RelativeThetaSEIIR(ODESys):
    """Customized SEIIR ODE system."""

    def __init__(self,
                 alpha: float,
                 sigma: float,
                 gamma1: float,
                 gamma2: float,
                 N: Union[int, float],
                 *args, **kwargs):
        """Constructor of CustomizedSEIIR.
        """
        self.alpha = alpha
        self.sigma = sigma
        self.gamma1 = gamma1
        self.gamma2 = gamma2
        self.N = N

        # create parameter names
        self.params = ['beta', 'theta']

        # create component names
        self.components = ['S', 'E', 'I1', 'I2', 'R']

        super().__init__(self.system, self.params, self.components, *args)

    def system(self, t: float, y: np.ndarray, p: np.ndarray) -> np.ndarray:
        """ODE System.
        """
        beta = p[0]
        theta = p[1]

        s = y[0]
        e = y[1]
        i1 = y[2]
        i2 = y[3]
        r = y[4]

        theta_plus = max(theta, 0.)
        theta_minus = -min(theta, 0.)

        new_e = beta*(s/self.N)*(i1 + i2)**self.alpha

        ds = -new_e - theta_plus*s
        de = new_e + theta_plus*s - self.sigma*e - theta_minus*e
        di1 = self.sigma*e - self.gamma1*i1
        di2 = self.gamma1*i1 - self.gamma2*i2
        dr = self.gamma2*i2 + theta_minus*e

        return np.array([ds, de, di1, di2, dr])


class _VaccineSEIIR(ODESys):
    """Customized SEIIR ODE system."""

    def __init__(self,
                 alpha: float,
                 sigma: float,
                 gamma1: float,
                 gamma2: float,
                 N: Union[int, float],
                 eta: float,
                 *args, **kwargs):
        """Constructor of CustomizedSEIIR.
        """
        self.alpha = alpha
        self.sigma = sigma
        self.gamma1 = gamma1
        self.gamma2 = gamma2
        self.N = N

        self.eta = eta  # Proportion effectively vaccinated

        # create parameter names
        self.params = ['beta', 'theta', 'psi']

        # create component names
        self.components = ['S', 'E', 'I1', 'I2', 'R',
                           'S_v', 'E_v', 'I1_v', 'I2_v', 'R_v']

        super().__init__(self.system, self.params, self.components, *args)

    def system(self, t: float, y: np.ndarray, p: np.ndarray) -> np.ndarray:
        """ODE System.
        """
        beta, theta, psi = p
        unvaccinated, vaccinated = y[:5], y[5:]
        s, e, i1, i2, r = unvaccinated
        s_v, e_v, i1_v, i2_v, r_v = vaccinated

        n_v = sum(vaccinated)
        i = i1 + i2 + i1_v + i2_v

        theta_plus = max(theta, 0.)
        theta_minus = -min(theta, 0.)

        psi_tilde = min(psi, n_v) / n_v
        psi_s = min(1 - beta * i**self.alpha / self.N - theta_plus, psi_tilde)
        psi_e = min(1 - self.sigma - theta_minus, psi_tilde)
        psi_i1 = min(1 - self.gamma1, psi_tilde)
        psi_i2 = min(1 - self.gamma2, psi_tilde)
        psi_r = psi_tilde

        phi = psi_s*s + psi_e*e + psi_i1*i1 + psi_i2*i2 + psi_r*r

        new_e = beta * s * i**self.alpha / self.N + theta_plus * s

        ds = -new_e - psi_s * s
        de = new_e - self.sigma*e - theta_minus*e - psi_e*e
        di1 = self.sigma*e - self.gamma1*i1 - psi_i1*i1
        di2 = self.gamma1*i1 - self.gamma2*i2 - psi_i2*i2
        dr = self.gamma2*i2 + theta_minus*e - psi_r*r

        new_e_v = beta * s_v * i**self.alpha / self.N + theta_plus * s_v
        ds_v = (1-self.eta)*psi_s * s - new_e_v
        de_v = new_e_v + (1-self.eta)*psi_e*e - self.sigma*e_v - theta_minus*e_v
        di1_v = self.sigma*e_v + (1-self.eta)*psi_i1*i1 - self.gamma1*i1_v
        di2_v = self.gamma1*i1_v + (1-self.eta)*psi_i2*i2 - self.gamma2*i2_v
        dr_v = self.gamma2*i2_v + theta_minus*e_v + self.eta*phi
        return np.array([ds, de, di1, di2, dr,
                         ds_v, de_v, di1_v, di2_v, dr_v])


class _SemiRelativeThetaSEIIR(ODESys):
    """Customized SEIIR ODE system."""

    def __init__(self,
                 alpha: float,
                 sigma: float,
                 gamma1: float,
                 gamma2: float,
                 N: Union[int, float],
                 delta: float,
                 *args):
        """Constructor of CustomizedSEIIR.
        """
        self.alpha = alpha
        self.sigma = sigma
        self.gamma1 = gamma1
        self.gamma2 = gamma2
        self.N = N
        self.delta = delta

        # create parameter names
        self.params = ['beta', 'theta']

        # create component names
        self.components = ['S', 'E', 'I1', 'I2', 'R']

        super().__init__(self.system, self.params, self.components, *args)

    def system(self, t: float, y: np.ndarray, p: np.ndarray) -> np.ndarray:
        """ODE System.
        """
        beta = p[0]
        theta = p[1]

        s = y[0]
        e = y[1]
        i1 = y[2]
        i2 = y[3]
        r = y[4]

        theta_plus = max(theta, 0.) * s / 1_000_000
        theta_minus = min(theta, 0.)
        theta_tilde = int(theta_plus != theta_minus)
        theta_minus_alt = (self.gamma1 - self.delta) * i1 - self.sigma * e - theta_plus
        effective_theta_minus = max(theta_minus, theta_minus_alt) * theta_tilde

        new_e = beta*(s/self.N)*(i1 + i2)**self.alpha

        ds = -new_e - theta_plus
        de = new_e - self.sigma*e
        di1 = self.sigma*e - self.gamma1*i1 + theta_plus + effective_theta_minus
        di2 = self.gamma1*i1 - self.gamma2*i2
        dr = self.gamma2 * i2 - effective_theta_minus

        return np.array([ds, de, di1, di2, dr])


@dataclass(frozen=True)
class _SeiirModelSpecs:
    alpha: float
    sigma: float
    gamma1: float
    gamma2: float
    N: float  # in case we want to do fractions, but not number of people
    delta: float = 0.1

    def __post_init__(self):
        assert 0 < self.alpha <= 1.0
        assert self.sigma >= 0.0
        assert self.gamma1 >= 0
        assert self.gamma2 >= 0
        assert self.N > 0
        assert self.delta > 0.0


class _ODERunner:

    def __init__(self, solver_name: str, seir_model: str, model_specs: _SeiirModelSpecs):
        if seir_model == 'old_theta':
            self.model = _SemiRelativeThetaSEIIR(**asdict(model_specs))
        elif seir_model == 'new_theta':
            self.model = _RelativeThetaSEIIR(**asdict(model_specs))
        elif seir_model == 'vaccine':
            self.model = _VaccineSEIIR(**asdict(model_specs))
        else:
            raise NotImplementedError(f'Unknown model type {seir_model}.')

        if solver_name == "RK45":
            self.solver = RK4(self.model.system, model_specs.delta)
        else:
            raise NotImplementedError(f"Unknown solver type {solver_name}.")

    def get_solution(self, initial_condition, times, beta, theta):
        solution = self.solver.solve(
            t=times,
            init_cond=initial_condition,
            t_params=times,
            params=np.vstack((beta, theta))
        )

        result_array = np.concatenate([
            solution,
            beta.reshape((1, -1)),
            theta.reshape((1, -1)),
            times.reshape((1, -1))
        ], axis=0).T

        result = pd.DataFrame(
            data=result_array,
            columns=self.model.components + self.model.params + ['t']
        )

        return result


def _beta_shift(beta_hat: pd.DataFrame,
                beta_scales: pd.DataFrame) -> pd.DataFrame:
    """Shift the raw predicted beta to line up with beta in the past.

    This method performs both an intercept shift and a scaling based on the
    residuals of the ode fit beta and the beta hat regression in the past.

    Parameters
    ----------
        beta_hat
            Dataframe containing the date, location_id, and beta hat in the
            future.
        beta_scales
            Dataframe containing precomputed parameters for the scaling.

    Returns
    -------
        Predicted beta, after scaling (shift).

    """
    beta_scales = beta_scales.set_index('location_id')
    beta_hat = beta_hat.sort_values(['location_id', 'date']).set_index('location_id')
    scale_init = beta_scales['scale_init']
    scale_final = beta_scales['scale_final']
    window_size = beta_scales['window_size']

    beta_final = []
    for location_id in beta_hat.index.unique():
        if window_size is not None:
            t = np.arange(len(beta_hat.loc[location_id])) / window_size.at[location_id]
            scale = scale_init.at[location_id] + (scale_final.at[location_id] - scale_init.at[location_id]) * t
            scale[(window_size.at[location_id] + 1):] = scale_final.at[location_id]
        else:
            scale = scale_init.at[location_id]
        loc_beta_hat = beta_hat.loc[location_id].set_index('date', append=True)['beta_pred']
        loc_beta_final = loc_beta_hat * scale
        beta_final.append(loc_beta_final)

    beta_final = pd.concat(beta_final).reset_index()

    return beta_final
