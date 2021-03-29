from cf_templates_lib import VPCTemplate
import sys
from pathlib import Path


if __name__ == "__main__":
    print(sys.argv)
    print(len(sys.argv))
    if len(sys.argv) != 6:
        raise ValueError("Expecting 6 values")
    proj_long, proj_short, region, stage_name, path = sys.argv[1:6]
    file_path = Path(__file__).absolute().parent.joinpath(path)
    directory = Path(file_path).parents[0]
    name = Path(file_path).name
    print(directory, name, file_path)
    VPCTemplate.set_class_variables(proj_long, proj_short, region, stage_name, template_output_dir=directory,)
    vpc = VPCTemplate("10.0.0.0/16")
    if 'prod' in stage_name.lower():
        vpc.add_prod_subnets()
    else:
        vpc.add_prod_subnets()
    vpc.save_template(name)
