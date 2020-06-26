import glob
import json
import logging
import os
import random
import string
import sys

from cfn_tools import load_yaml, dump_yaml

logger = logging.getLogger(__name__)
stdout = logging.StreamHandler(sys.stdout)
stdout.setFormatter(logging.Formatter('%(message)s'))
stdout.setLevel(logging.INFO)
logger.addHandler(stdout)
logger.setLevel(logging.INFO)


class UpdateTemplates:
    STAGE_NAMES_AND_CONFIGS = ()

    @staticmethod
    def _random_generator(size=3, chars=string.ascii_lowercase):
        return ''.join(random.choice(chars) for x in range(size)).title()

    # better names
    def __init__(self, templates_path, policies_base_path, updated_templates_path, stage_name):
        self.templates_path = templates_path
        self.policies_base_path = policies_base_path
        self.updated_templates_path = updated_templates_path
        self.stage_name = stage_name
        self.template_list = ['master', 'cluster', 'scheduler', 'webserver', 'workerset']
        self.templates_dict = dict()
        self._load_templates()
        self.random_string = self._random_generator()

    def update_instance_types(self):
        if self.STAGE_NAMES_AND_CONFIGS:
            # First check that the stage matches, then check if a custom instance type is defined for that stage
            if self.stage_name in self.STAGE_NAMES_AND_CONFIGS:
                if "worker_instance_type" in self.STAGE_NAMES_AND_CONFIGS[self.stage_name]:
                    instance_type = self.STAGE_NAMES_AND_CONFIGS[self.stage_name]["worker_instance_type"]
                    logger.info("Updating templates to use {} as worker instance type from class attribute".format(
                        instance_type))
                    self.templates_dict["master"]["Parameters"]["WorkerInstanceType"]["Default"] = instance_type
                else:
                    logger.info("No worker_instance_type detected")
        return

    @staticmethod
    def to_pascal_case(filename):
        split_name = filename.split('-')
        return ''.join(map(str.title, split_name))

    def _load_templates(self):
        for template_name in self.template_list:
            with open(os.path.join(self.templates_path,
                                   "turbine-{}.template".format(template_name))) as infile:
                self.templates_dict[template_name] = load_yaml(infile)

    def save_templates(self):
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
                        policy_loaded["Statement"]["Resource"] = [{'Fn::Sub': resource} for resource in policy_loaded["Statement"]["Resource"]]
                        policy_name = policy_path.rsplit('/')[-1].split('.')[0]
                        new_policy = {'PolicyName': {
                            'Fn::Sub': '{policy_name}-{stage_name}-{nesting}'.format(policy_name=policy_name,
                                                                                     stage_name=self.stage_name,
                                                                                     nesting=template_name)},
                            'PolicyDocument': {'Fn::Sub': policy_loaded}}

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

    def add_template(self, additional_template_path, parameters_and_vals={}):

        with open(additional_template_path) as template_file:
            # Load yaml used for now but this can be changed if need be
            additional_template = load_yaml(template_file.read())

        if 'Parameters' in additional_template.keys():
            template_params = {key: value for key, value in additional_template['Parameters'].items() if
                               key not in parameters_and_vals.keys()}
            add_keys_list = additional_template['Parameters'].keys()
            resource_params = {param: {'Ref': param} for param in additional_template['Parameters'].keys() if
                               param not in parameters_and_vals.keys()}

            resource_params = {**resource_params, **parameters_and_vals}

        else:
            if parameters_and_vals:
                raise ValueError('There are no input parameters on the template can not pass in extra_param_values')
            template_params = {}
            add_keys_list = []
            resource_params = None

        existing_keys_lists = self.templates_dict['master']['Parameters'].keys()

        overlapped_keys = [new_key for new_key in existing_keys_lists if new_key in add_keys_list]
        if len(overlapped_keys):
            raise KeyError(
                'There is an overlap in parameters between the additional template and the master template. {}'.format(
                    str(overlapped_keys)))

        # Use filename converted to PascalCase to set the name of the stack resource
        template_file_name = additional_template_path.rsplit('.', 1)[0].rsplit('/', 1)[-1]
        sub_stack_name = self.to_pascal_case(template_file_name)

        template_path_s3 = 'templates/additional_templates/' + additional_template_path.rsplit('/')[-1]
        template_url = {'Fn::Join': ['', [{'Fn::Sub': 'https://${QSS3BucketName}.s3.amazonaws.com/'},
                                          {'Ref': 'QSS3KeyPrefix'}, template_path_s3]]}

        self.templates_dict['master']['Parameters'] = {**self.templates_dict['master']['Parameters'],
                                                       **template_params}
        if resource_params:
            resource_add = {sub_stack_name: {'Type': 'AWS::CloudFormation::Stack',
                                             'Properties': {'TemplateURL': template_url,
                                                            'Parameters': resource_params}}}
        else:
            resource_add = {sub_stack_name: {'Type': 'AWS::CloudFormation::Stack',
                                             'Properties': {'TemplateURL': template_url}}}

        self.templates_dict['master']['Resources'].update(resource_add)

    def update_templates(self, additional_template_path=None):
        self.add_policies()
        if additional_template_path:
            self.add_template(additional_template_path,
                              parameters_and_vals={"VpcId": {"Fn::GetAtt": ["VPCStack", "Outputs.VPCID"]}})
        self.save_templates()
