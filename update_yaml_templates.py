import json
import os
import sys
import glob
import logging
from cfn_tools import load_yaml, dump_yaml

logger = logging.getLogger(__name__)
stdout = logging.StreamHandler(sys.stdout)
stdout.setFormatter(logging.Formatter('%(message)s'))
stdout.setLevel(logging.INFO)
logger.addHandler(stdout)
logger.setLevel(logging.INFO)


def update_templates(templates_path, policies_base_path, updated_templates_path, stage_name):
    template_list = ['master', 'cluster', 'scheduler', 'webserver', 'workerset']
    templates_dict = {}

    for template_name in template_list:
        with open(os.path.join(templates_path,
                               "turbine-{}.template".format(template_name))) as infile:

            templates_dict[template_name] = load_yaml(infile)

        policies_list = glob.glob(os.path.join(policies_base_path, template_name, '*.json'))

        if policies_list:
            for policy_path in policies_list:
                with open(policy_path) as policy:
                    policy_loaded = json.load(policy)
                    policy_name = policy_path.rsplit('/')[-1].split('.')[0]
                    new_policy = {'PolicyName': {
                        'Fn::Sub': '{policy_name}-{stage_name}-{nesting}'.format(policy_name=policy_name,
                                                                                 stage_name=stage_name,
                                                                                 nesting=template_name)},
                        'PolicyDocument': policy_loaded}

                    templates_dict[template_name]['Resources']['IamRole']['Properties']['Policies'].append(new_policy)

        managed_policies = glob.glob(os.path.join(
            policies_base_path, template_name, 'managed_policies.txt'
        ))
        if managed_policies:
            with open(managed_policies[0]) as m_policies:
                arn_list = m_policies.read().splitlines()
                arn_list = [{'Fn::Sub': x} for x in arn_list]
                templates_dict[template_name]['Resources']['IamRole']['Properties']['ManagedPolicyArns'] += arn_list

    for template_name in template_list:
        with open(os.path.join(updated_templates_path,
                               "turbine-{}.template".format(template_name)), 'w') as outfile:
            outfile.write(dump_yaml(templates_dict[template_name]))


if __name__ == "__main__":

    """
    Get command line arguments
    """

    EXPECTED_ARG_COUNT = 5
    if len(sys.argv) != EXPECTED_ARG_COUNT:

        logger.error(
            "Cannot generate templates. Incorrect number of arguments: {} given, {} expected".format(
                len(sys.argv), EXPECTED_ARG_COUNT) + str(sys.argv))
        raise ValueError(
            "Cannot generate templates. Incorrect number of arguments: {} given, {} expected".format(
                len(sys.argv), EXPECTED_ARG_COUNT) + str(sys.argv))
    else:
        for argnum, arg in enumerate(sys.argv):
            if not arg:
                raise ValueError("Blank value found for {}".format(argnum))

    TEMPLATES_PATH = str(sys.argv[1])
    POLICIES_BASE_PATH = str(sys.argv[2])
    UPDATED_TEMPLATES_PATH = str(sys.argv[3])
    STAGE_NAME = str(sys.argv[4])

    update_templates(TEMPLATES_PATH, POLICIES_BASE_PATH, UPDATED_TEMPLATES_PATH, STAGE_NAME)
