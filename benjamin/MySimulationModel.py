import re
import os
import numpy as np

from subprocess import check_output
from shutil import copytree
from shutil import rmtree

from pygpc.SimulationModel import AbstractModel

class MyModel(AbstractModel):
    # OF_CASE_DIR = "/home/kalloch/OpenFOAM/kalloch-3.0.1/run/PyGPC_head"
    OF_CASE_DIR_BASE = "/home/kalloch/OpenFOAM/kalloch-3.0.1/run/PyGPC_LI0315593X_WML"

    def __init__(self, conductivities, context):
        super(MyModel, self).__init__(context)

        self.conductivities = conductivities

    def simulate(self, process_id):
        OF_CASE_DIR = MyModel.OF_CASE_DIR_BASE + "_" + repr(process_id)

        scalp_cond = repr(self.conductivities[0])
        skull_cond = repr(self.conductivities[1])
        gm_cond = repr(self.conductivities[2])
        wm_cond = repr(self.conductivities[3])
        lesion_cond = repr(self.conductivities[4])

        # Step 1: setup the case directory by replacing the conductivities with the ones provided by the PyGPC framework
        rmtree(OF_CASE_DIR + "/0", ignore_errors=True)
        copytree(OF_CASE_DIR + "/0_clean", OF_CASE_DIR + "/0")

        with open(OF_CASE_DIR + "/0/sigma") as f:
            sigma = f.read()

        sigma = sigma.replace("%SKIN_VAL%", scalp_cond)
        sigma = sigma.replace("%SKULL_VAL%", skull_cond)
        sigma = sigma.replace("%CSF_VAL%", "1.65")
        sigma = sigma.replace("%GM_VAL%", gm_cond)
        sigma = sigma.replace("%WM_VAL%", wm_cond)
        sigma = sigma.replace("%LESION_VAL%", lesion_cond)
        sigma = sigma.replace("%AIR_VAL%", "1e-15")
        sigma = sigma.replace("%ELECTRODE_VAL%", "1.4")

        with open(OF_CASE_DIR + "/0/sigma", "w") as f:
            f.write(sigma)

        # Step 2: run the simulation
        # The script is located in the case-dir and we need to provide the case-dir as an argument to the solver application
        stdout_string = check_output(["bash " + OF_CASE_DIR + "/runSim.sh " + OF_CASE_DIR], shell=True)

        # We must check the number of iterations, because the simualtion results will be stored in a
        # directory with that number
        #print "*************************************** Solver output - start *************************************"
        #print stdout_string
        #print "*************************************** Solver output - end *************************************"

        regex_result = re.search("SIMPLE solution converged in ([0-9]+) iterations", stdout_string);
        num_iterations = int(regex_result.group(1))

        # Step 3: Query the results
        internal_field_flag = False
        num_lines_to_read = -1

        with open(OF_CASE_DIR + "/" + repr(num_iterations + 1) + "/ElPot") as f:
            for line in f:
                if "internalField" in line:
                    num_lines_to_read = int(next(f))
                    next(f)
                    break

            ElPot = np.zeros(num_lines_to_read, dtype='float64')

            for i in range(0, num_lines_to_read):
                ElPot[i] = float(next(f))

            return ElPot

        return np.array([])

    @staticmethod
    def write_result_field(fieldName, data):
        out_dir = MyModel.OF_CASE_DIR_BASE + "/999/"

        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        with open(MyModel.OF_CASE_DIR_BASE + "/Field_template") as f:
            template = f.read()

        data_str = np.char.mod('%f', data)
        data_str = "\n".join(data_str)

        template = template.replace("%FIELDNAME%", fieldName)
        template = template.replace("%NUM_VALUES%", repr(len(data)))
        template = template.replace("%DATA%", data_str)

        with open(out_dir + "/" + fieldName, "w") as f:
            f.write(template)
