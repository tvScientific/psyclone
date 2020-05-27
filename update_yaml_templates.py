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


class UpdateTemplates:
    def __init__(self, templates_path, policies_base_path, updated_templates_path, stage_name,
                 additional_templates_path):
        self.templates_path = templates_path
        self.policies_base_path = policies_base_path
        self.updated_templates_path = updated_templates_path
        self.additional_templates_path = additional_templates_path
        self.stage_name = stage_name
        self.template_list = ['master', 'cluster', 'scheduler', 'webserver', 'workerset']
        self.templates_dict = dict()
        self._load_templates()

    @staticmethod
    def to_pascal_case(filename):
        split_name = filename.split('-')
        return ''.join(map(str.title, split_name))

    def _load_templates(self):
        for template_name in self.template_list:
            with open(os.path.join(self.templates_path,
                                   "turbine-{}.template".format(template_name))) as infile:
                self.templates_dict[template_name] = load_yaml(infile)

    def _save_templates(self):
        for template_name in self.templates_dict.keys():
            with open(os.path.join(self.updated_templates_path,
                                   "turbine-{}.template".format(template_name)), 'w') as outfile:
                outfile.write(dump_yaml(self.templates_dict[template_name]))

    def add_policies(self):

        for template_name in self.templates_dict.keys():
            policies_list = glob.glob(os.path.join(self.policies_base_path, template_name, '*.json'))

            if policies_list:
                for policy_path in policies_list:
                    with open(policy_path) as policy:
                        policy_loaded = json.load(policy)
                        policy_name = policy_path.rsplit('/')[-1].split('.')[0]
                        new_policy = {'PolicyName': {
                            'Fn::Sub': '{policy_name}-{stage_name}-{nesting}'.format(policy_name=policy_name,
                                                                                     stage_name=self.stage_name,
                                                                                     nesting=template_name)},
                            'PolicyDocument': policy_loaded}

                        self.templates_dict[template_name]['Resources']['IamRole']['Properties']['Policies'].append(
                            new_policy)

            managed_policies = glob.glob(os.path.join(
                self.policies_base_path, template_name, 'managed_policies.txt'
            ))
            if managed_policies:
                with open(managed_policies[0]) as m_policies:
                    arn_list = m_policies.read().splitlines()
                    arn_list = [{'Fn::Sub': x} for x in arn_list]
                    self.templates_dict[template_name]['Resources']['IamRole']['Properties'][
                        'ManagedPolicyArns'] += arn_list

    def _add_templates(self):

        with open(self.additional_templates_path) as template_file:
            # Load yaml used for now but this can be changed if need be
            additional_template = load_yaml(template_file.read())

        template_params = additional_template['Parameters']
        # Use filename converted to PascalCase to set the name of the stack resource
        template_file_name = self.additional_templates_path.rsplit('.')[0].rsplit('/')[-1]
        sub_stack_name = self.to_pascal_case(template_file_name)

        add_keys_list = additional_template['Parameters'].keys()
        existing_keys_lists = self.templates_dict['master']['Parameters'].keys()

        if any((True for new_key in existing_keys_lists if new_key in add_keys_list)):
            raise KeyError('There is an overlap in parameters between the additional template and the master template')

        template_path_s3 = 'additional_templates/' + template_file_name
        template_url = {'Fn::Join': ['', [{'Fn::Sub': 'https://${QSS3BucketName}.s3.amazonaws.com/'},
                                          {'Ref': 'QSS3KeyPrefix'}, template_path_s3]]}

        self.templates_dict['master']['Parameters'] = {**self.templates_dict['master']['Parameters'],
                                                       **template_params}
        resource_add = {sub_stack_name: {'Type': 'AWS::CloudFormation::Stack',
                                         'Properties': {'TemplateURL': template_url, 'Parameters': template_params}}}

        self.templates_dict['master']['Resources'].update(resource_add)

    def update_templates(self):
        self._load_templates()
        self.add_policies()
        if self.additional_templates_path:
            self._add_templates()
        self._save_templates()


if __name__ == "__main__":

    """
    Get command line arguments
    """
    blank_acceptable = [4, 5]

    EXPECTED_ARG_COUNT = 6
    if len(sys.argv) != EXPECTED_ARG_COUNT:

        logger.error(
            "Cannot generate templates. Incorrect number of arguments: {} given, {} expected".format(
                len(sys.argv), EXPECTED_ARG_COUNT) + str(sys.argv))
        raise ValueError(
            "Cannot generate templates. Incorrect number of arguments: {} given, {} expected".format(
                len(sys.argv), EXPECTED_ARG_COUNT) + str(sys.argv))
    else:
        for argnum, arg in enumerate(sys.argv):
            if not arg and argnum not in blank_acceptable:
                raise ValueError("Blank value found for {}".format(argnum))

    TEMPLATES_PATH = str(sys.argv[1])
    UPDATED_TEMPLATES_PATH = str(sys.argv[2])
    STAGE_NAME = str(sys.argv[3])
    POLICIES_BASE_PATH = str(sys.argv[4])
    ADDITIONAL_TEMPLATES_PATH = str(sys.argv[5])

    update_templates = UpdateTemplates(TEMPLATES_PATH, POLICIES_BASE_PATH, UPDATED_TEMPLATES_PATH, STAGE_NAME,
                                       ADDITIONAL_TEMPLATES_PATH)
    update_templates.update_templates()
