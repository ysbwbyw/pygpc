import time
import random
import numpy as np
import scipy.stats
from .GPC import *
from .io import iprint, wprint
from .misc import display_fancy_bar
from .misc import get_array_unique_rows
from .Basis import *


class SGPC(GPC):
    """
    Sub-class for standard gPC (SGPC)

    Attributes
    ----------
    order: list of int [dim]
        Maximum individual expansion order [order_1, order_2, ..., order_dim].
        Generates individual polynomials also if maximum expansion order in order_max is exceeded
    order_max: int
        Maximum global expansion order (sum of all exponents).
        The maximum expansion order considers the sum of the orders of combined polynomials only
    interaction_order: int
        Number of random variables, which can interact with each other.
        All polynomials are ignored, which have an interaction order greater than the specified
    interaction_order_current: int
        Number of random variables, which can interact with each other.
        All polynomials are ignored, which have an interaction order greater than the specified
        Current interaction order counter (only used in case of adaptive algorithms)
    fn_results : string, optional, default=None
        If provided, model evaluations are saved in fn_results.hdf5 file and gpc object in fn_results.pkl file
    """

    def __init__(self, problem, order, order_max, interaction_order, fn_results=None):
        """
        Constructor; Initializes the SGPC class

        Parameters
        ----------
        problem: Problem class instance
            GPC Problem under investigation
        order: list of int [dim]
            Maximum individual expansion order [order_1, order_2, ..., order_dim].
            Generates individual polynomials also if maximum expansion order in order_max is exceeded
        order_max: int
            Maximum global expansion order (sum of all exponents).
            The maximum expansion order considers the sum of the orders of combined polynomials only
        interaction_order: int
            Number of random variables, which can interact with each other.
            All polynomials are ignored, which have an interaction order greater than the specified
        fn_results : string, optional, default=None
            If provided, model evaluations are saved in fn_results.hdf5 file and gpc object in fn_results.pkl file
        """
        super(SGPC, self).__init__(problem, fn_results)

        self.order = order
        self.order_max = order_max
        self.interaction_order = interaction_order
        self.interaction_order_current = interaction_order

        self.basis = Basis()
        self.basis.init_basis_sgpc(problem=problem,
                                   order=order,
                                   order_max=order_max,
                                   interaction_order=interaction_order)

    @staticmethod
    def get_mean(coeffs):
        """
        Calculate the expected mean value.

        mean = SGPC.get_mean(coeffs)

        Parameters
        ----------
        coeffs: ndarray of float [n_basis x n_out]
            GPC coefficients

        Returns
        -------
        mean: ndarray of float [1 x n_out]
            Expected value of output quantities
        """

        mean = coeffs[0]
        # TODO: check if 1-dimensional array should be (N,) or (N,1)
        # mean = mean[np.newaxis, :]
        return mean

    @staticmethod
    def get_standard_deviation(coeffs):
        """
        Calculate the standard deviation.

        std = SGPC.get_standard_deviation(coeffs)

        Parameters
        ----------
        coeffs: ndarray of float [n_basis x n_out]
            GPC coefficients

        Returns
        -------
        std: ndarray of float [1 x n_out]
            Standard deviation of output quantities
        """

        std = np.sqrt(np.sum(np.square(coeffs[1:]), axis=0))
        # TODO: check if 1-dimensional array should be (N,) or (N,1)
        # std = std[np.newaxis, :]
        return std

    # noinspection PyTypeChecker
    def get_sobol_indices(self, coeffs):
        """
        Calculate the available sobol indices.

        sobol, sobol_idx = SGPC.get_sobol_indices(coeffs)

        Parameters
        ----------
        coeffs:  ndarray of float [n_basis x n_out]
            GPC coefficients

        Returns
        -------
        sobol: ndarray of float [n_sobol x n_out]
            Unnormalized Sobol indices
        sobol_idx: list of ndarray of int [n_sobol x (n_sobol_included)]
            Parameter combinations in rows of sobol.
        sobol_idx_bool: ndarray of bool [n_sobol x dim]
            Boolean mask which contains unique multi indices.
        """

        iprint("Determining Sobol indices...")

        # handle (N,) arrays
        if len(coeffs.shape) == 1:
            n_out = 1
        else:
            n_out = coeffs.shape[1]

        n_coeffs = coeffs.shape[0]

        if n_coeffs == 1:
            raise Exception('Number of coefficients is 1 ... no sobol indices to calculate ...')

        # Generate boolean matrix of all basis functions where order > 0 = True
        # size: [n_basis x dim]
        multi_indices = np.array([map(lambda _b:_b.p["i"], b_row) for b_row in self.basis.b])
        sobol_mask = multi_indices != 0

        # look for unique combinations (i.e. available sobol combinations)
        # size: [N_sobol x dim]
        sobol_idx_bool = get_array_unique_rows(sobol_mask)

        # delete the first row where all polynomials are order 0 (no sensitivity)
        sobol_idx_bool = np.delete(sobol_idx_bool, [0], axis=0)
        n_sobol_available = sobol_idx_bool.shape[0]

        # check which basis functions contribute to which sobol coefficient set
        # True for specific coeffs if it contributes to sobol coefficient
        # size: [N_coeffs x N_sobol]
        sobol_poly_idx = np.zeros([n_coeffs, n_sobol_available])

        for i_sobol in range(n_sobol_available):
            sobol_poly_idx[:, i_sobol] = np.all(sobol_mask == sobol_idx_bool[i_sobol], axis=1)

        # calculate sobol coefficients matrix by summing up the individual
        # contributions to the respective sobol coefficients
        # size [N_sobol x N_points]
        sobol = np.zeros([n_sobol_available, n_out])

        for i_sobol in range(n_sobol_available):
            sobol[i_sobol] = np.sum(np.square(coeffs[sobol_poly_idx[:, i_sobol] == 1]), axis=0)

        # sort sobol coefficients in descending order (w.r.t. first output only ...)
        idx_sort_descend_1st = np.argsort(sobol[:, 0], axis=0)[::-1]
        sobol = sobol[idx_sort_descend_1st, :]
        sobol_idx_bool = sobol_idx_bool[idx_sort_descend_1st]

        # get list of sobol indices
        sobol_idx = [0 for _ in range(sobol_idx_bool.shape[0])]

        for i_sobol in range(sobol_idx_bool.shape[0]):
            sobol_idx[i_sobol] = np.array([i for i, x in enumerate(sobol_idx_bool[i_sobol, :]) if x])

        return sobol, sobol_idx, sobol_idx_bool

    def get_sobol_composition(self, sobol, sobol_idx, sobol_idx_bool):
        """
        Determine average ratios of Sobol indices over all output quantities:
        (i) over all orders and (e.g. 1st: 90%, 2nd: 8%, 3rd: 2%)
        (ii) for the 1st order indices w.r.t. each random variable. (1st: x1: 50%, x2: 40%)

        sobol, sobol_idx, sobol_rel_order_mean, sobol_rel_order_std, sobol_rel_1st_order_mean, sobol_rel_1st_order_std
        = SGPC.get_sobol_composition(coeffs, sobol, sobol_idx, sobol_idx_bool)

        Parameters
        ----------
        sobol: ndarray of float [n_sobol x n_out]
            Unnormalized sobol_indices
        sobol_idx: list of ndarray [n_sobol x (n_sobol_included)]
            Parameter combinations in rows of sobol.
        sobol_idx_bool: list of ndarray of bool
            Boolean mask which contains unique multi indices.

        Returns
        -------
        sobol_rel_order_mean: ndarray of float [n_out]
            Average proportion of the Sobol indices of the different order to the total variance (1st, 2nd, etc..,),
            (over all output quantities)
        sobol_rel_order_std: ndarray of float [n_out]
            Standard deviation of the proportion of the Sobol indices of the different order to the total variance
            (1st, 2nd, etc..,), (over all output quantities)
        sobol_rel_1st_order_mean: ndarray of float [n_out]
            Average proportion of the random variables of the 1st order Sobol indices to the total variance,
            (over all output quantities)
        sobol_rel_1st_order_std: ndarray of float [n_out]
            Standard deviation of the proportion of the random variables of the 1st order Sobol indices to the total
            variance
            (over all output quantities)
        """

        # get max order
        order_max = np.max(np.sum(sobol_idx_bool, axis=1))

        # total variance
        var = np.sum(sobol, axis=0).flatten()

        # get NaN values
        not_nan_mask = np.logical_not(np.isnan(var))

        sobol_rel_order_mean = []
        sobol_rel_order_std = []
        sobol_rel_1st_order_mean = []
        sobol_rel_1st_order_std = []
        str_out = []

        # get maximum length of random_vars label
        max_len = max([len(self.problem.random_vars[i]) for i in range(len(self.problem.random_vars))])

        for i in range(order_max):
            # extract sobol coefficients of order i
            sobol_extracted, sobol_extracted_idx = self.get_extracted_sobol_order(sobol, sobol_idx, i + 1)

            # determine average sobol index over all elements
            sobol_rel_order_mean.append(np.sum(np.sum(sobol_extracted[:, not_nan_mask], axis=0).flatten()) /
                                        np.sum(var[not_nan_mask]))

            sobol_rel_order_std.append(np.std(np.sum(sobol_extracted[:, not_nan_mask], axis=0).flatten() /
                                              var[not_nan_mask]))

            iprint("Ratio: Sobol indices order {} / total variance: {:.4f} +- {:.4f}"
                   .format(i+1, sobol_rel_order_mean[i], sobol_rel_order_std[i]), tab=1, verbose=self.verbose)

            # for first order indices, determine ratios of all random variables
            if i == 0:
                # deep copy
                sobol_extracted_idx_1st = sobol_extracted_idx[:]
                for j in range(sobol_extracted.shape[0]):
                    sobol_rel_1st_order_mean.append(np.sum(sobol_extracted[j, not_nan_mask].flatten())
                                                    / np.sum(var[not_nan_mask]))
                    sobol_rel_1st_order_std.append(0)

                    str_out.append("\t{}{}: {:.4f}"
                                   .format((max_len - len(self.problem.random_vars[sobol_extracted_idx_1st[j]])) * ' ',
                                           self.problem.random_vars[sobol_extracted_idx_1st[j]],
                                           sobol_rel_1st_order_mean[j]))

        sobol_rel_order_mean = np.array(sobol_rel_order_mean)
        sobol_rel_1st_order_mean = np.array(sobol_rel_1st_order_mean)

        # print output of 1st order Sobol indices ratios of parameters
        if self.verbose:
            for j in range(len(str_out)):
                print(str_out[j])

        return sobol_rel_order_mean, sobol_rel_order_std, \
               sobol_rel_1st_order_mean, sobol_rel_1st_order_std

    @staticmethod
    def get_extracted_sobol_order(sobol, sobol_idx, order=1):
        """
        Extract Sobol indices with specified order from Sobol data.

        sobol_1st, sobol_idx_1st = SGPC.get_extracted_sobol_order(sobol, sobol_idx, order=1)

        Parameters
        ----------
        sobol: ndarray of float [n_sobol x n_out]
            Sobol indices of n_out output quantities
        sobol_idx: list or ndarray of int [n_sobol]
            Parameter label indices belonging to Sobol indices
        order: int, optional, default=1
            Sobol index order to extract

        Returns
        -------
        sobol_n_order: ndarray of float [n_out]
            n-th order Sobol indices of n_out output quantities
        sobol_idx_n_order: ndarray of int
            Parameter label indices belonging to n-th order Sobol indices
        """

        # make mask of nth order sobol indices
        mask = [index for index, sobol_element in enumerate(sobol_idx) if sobol_element.shape[0] == order]

        # extract from dataset
        sobol_n_order = sobol[mask, :]
        sobol_idx_n_order = np.vstack(sobol_idx[mask])

        # sort sobol indices according to parameter indices in ascending order
        sort_idx = np.argsort(sobol_idx_n_order, axis=0)[:, 0]
        sobol_n_order = sobol_n_order[sort_idx, :]
        sobol_idx_n_order = sobol_idx_n_order[sort_idx, :]

        return sobol_n_order, sobol_idx_n_order

    # noinspection PyTypeChecker
    def get_global_sens(self, coeffs):
        """
        Determine the global derivative based sensitivity coefficients after Xiu (2009) [1].

        global_sens = SGPC.get_global_sens(coeffs)

        Parameters
        ----------
        coeffs: ndarray of float [n_basis x n_out]
            GPC coefficients

        Returns
        -------
        global_sens: ndarray [dim x n_out]
            Global derivative based sensitivity coefficients

        Notes
        -----
        .. [1] D. Xiu, Fast Numerical Methods for Stochastic Computations: A Review,
           Commun. Comput. Phys., 5 (2009), pp. 242-272 eq. (3.14) page 255
        """

        b_int_global = np.zeros([self.problem.dim, self.basis.n_basis])

        # construct matrix with integral expressions [n_basis x dim]
        b_int = np.array([map(lambda _b: _b.fun_int, b_row) for b_row in self.basis.b])
        b_int_der = np.array([map(lambda _b: _b.fun_der_int, b_row) for b_row in self.basis.b])

        for i_sens in range(self.problem.dim):
            # replace column with integral expressions from derivative of parameter[i_dim]
            tmp = copy.deepcopy(b_int)
            tmp[:, i_sens] = b_int_der[:, i_sens]

            # determine global integral expression
            b_int_global[i_sens, :] = np.prod(tmp, axis=1)

        global_sens = np.dot(b_int_global, coeffs)
        # global_sens = np.dot(b_int_global, coeffs) / (2 ** self.problem.dim)

        return global_sens

    # noinspection PyTypeChecker
    def get_local_sens(self, coeffs, x):
        """
        Determine the local derivative based sensitivity coefficients in the point of interest x
        (normalized coordinates [-1, 1]).

        local_sens = SGPC.calc_localsens(coeffs, x)

        Parameters
        ----------
        coeffs: ndarray of float [n_basis x n_out]
            GPC coefficients
        x: ndarray of float [n_basis x n_out]
            Point in variable space to evaluate local sensitivity in (normalized coordinates [-1, 1])

        Returns
        -------
        local_sens: ndarray [dim x n_out]
            Local sensitivity of output quantities in point x
        """

        b_x_global = np.zeros([self.problem.dim, self.basis.n_basis])

        # evaluate fun(x) and fun_der(x) at point of operation x [n_basis x dim]
        b_x = np.array([map(lambda _b: _b.fun(x), b_row) for b_row in self.basis.b])
        b_der_x = np.array([map(lambda _b: _b.fun_der(x), b_row) for b_row in self.basis.b])

        for i_sens in range(self.problem.dim):
            # replace column with integral expressions from derivative of parameter[i_dim]
            tmp = copy.deepcopy(b_x)
            tmp[:, i_sens] = b_der_x[:, i_sens]

            # determine global integral expression
            b_x_global[i_sens, :] = np.prod(tmp, axis=1)

        local_sens = np.dot(b_x_global, coeffs)

        return local_sens


class Reg(SGPC):
    """
    Regression gPC subclass

    Reg(pdf_type, pdf_shape, limits, order, order_max, interaction_order, grid, random_vars=None)

    Attributes
    ----------
    relative_error_loocv: list of float
        relative error of the leave-one-out-cross-validation
    solver: str
        Solver to determine the gPC coefficients
        - 'Moore-Penrose' ... Pseudoinverse of gPC matrix (SGPC.Reg, EGPC)
        - 'OMP' ... Orthogonal Matching Pursuit, sparse recovery approach (SGPC.Reg, EGPC)
        - 'NumInt' ... Numerical integration, spectral projection (SGPC.Quad)
    settings: dict
        Solver settings
        - 'Moore-Penrose' ... None
        - 'OMP' ... {"n_coeffs_sparse": int} Number of gPC coefficients != 0
        - 'NumInt' ... None
    """

    def __init__(self, problem, order, order_max, interaction_order, fn_results=None):
        """
        Constructor; Initializes Regression SGPC class

        Parameters
        ----------
        problem: Problem class instance
            GPC Problem under investigation
        order: list of int [dim]
            Maximum individual expansion order [order_1, order_2, ..., order_dim].
            Generates individual polynomials also if maximum expansion order in order_max is exceeded
        order_max: int
            Maximum global expansion order (sum of all exponents).
            The maximum expansion order considers the sum of the orders of combined polynomials only
        interaction_order: int
            Number of random variables, which can interact with each other.
            All polynomials are ignored, which have an interaction order greater than the specified
        fn_results : string, optional, default=None
            If provided, model evaluations are saved in fn_results.hdf5 file and gpc object in fn_results.pkl file
        """
        super(Reg, self).__init__(problem, order, order_max, interaction_order, fn_results)
        self.solver = 'Moore-Penrose'   # Default solver
        self.settings = None            # Default Solver settings
        self.relative_error_loocv = []

    def loocv(self, sim_results, solver, settings):
        """
        Perform leave one out cross validation of gPC with maximal 100 points
        and add result to self.relative_error_loocv.

        relative_error_loocv = SGPC.loocv(sim_results)

        Parameters
        ----------
        sim_results: ndarray of float [n_grid x n_out]
            Results from n_grid simulations with n_out output quantities
        solver: str
            Solver to determine the gPC coefficients
            - 'Moore-Penrose' ... Pseudoinverse of gPC matrix (SGPC.Reg, EGPC)
            - 'OMP' ... Orthogonal Matching Pursuit, sparse recovery approach (SGPC.Reg, EGPC)
            - 'NumInt' ... Numerical integration, spectral projection (SGPC.Quad)
        settings: dict
            Solver settings
            - 'Moore-Penrose' ... None
            - 'OMP' ... {"n_coeffs_sparse": int} Number of gPC coefficients != 0
            - 'NumInt' ... None

        Returns
        -------
        relative_error_loocv: float
            Relative mean error of leave one out cross validation
        """

        # define number of performed cross validations (max 100)
        n_loocv_points = np.min((sim_results.shape[0], 100))

        # make list of indices, which are randomly sampled
        loocv_point_idx = random.sample(list(range(sim_results.shape[0])), n_loocv_points)

        start = time.time()
        relative_error = np.zeros(n_loocv_points)
        for i in range(n_loocv_points):
            # get mask of eliminated row
            mask = np.arange(sim_results.shape[0]) != loocv_point_idx[i]

            # determine gpc coefficients (this takes a lot of time for large problems)
            coeffs_loo = self.solve(sim_results=sim_results[mask, :],
                                    solver=solver,
                                    settings=settings,
                                    gpc_matrix=self.gpc_matrix[mask, :])

            sim_results_temp = sim_results[loocv_point_idx[i], :]
            relative_error[i] = scipy.linalg.norm(sim_results_temp - np.dot(self.gpc_matrix[loocv_point_idx[i], :],
                                                                            coeffs_loo))\
                                / scipy.linalg.norm(sim_results_temp)
            display_fancy_bar("LOOCV", int(i + 1), int(n_loocv_points))

        # store result in relative_error_loocv
        self.relative_error_loocv.append(np.mean(relative_error))
        iprint(" (" + str(time.time() - start) + ")")

        return self.relative_error_loocv[-1]


class Quad(SGPC):
    """
    Quadrature SGPC sub-class
    """

    def __init__(self, problem, order, order_max, interaction_order, fn_results=None):
        """
        Constructor; Initializes Quadrature SGPC sub-class

        Quad(problem, order, order_max, interaction_order)

        Parameters
        ----------
        problem: Problem class instance
            GPC Problem under investigation
        order: list of int [dim]
            Maximum individual expansion order [order_1, order_2, ..., order_dim].
            Generates individual polynomials also if maximum expansion order in order_max is exceeded
        order_max: int
            Maximum global expansion order (sum of all exponents).
            The maximum expansion order considers the sum of the orders of combined polynomials only
        interaction_order: int
            Number of random variables, which can interact with each other.
            All polynomials are ignored, which have an interaction order greater than the specified
        fn_results : string, optional, default=None
            If provided, model evaluations are saved in fn_results.hdf5 file and gpc object in fn_results.pkl file
        """
        super(Quad, self).__init__(problem, order, order_max, interaction_order, fn_results)
        self.solver = 'NumInt'  # Default solver
        self.settings = None    # Default solver settings