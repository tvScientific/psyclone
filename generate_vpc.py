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

    print(proj_long, proj_short, region, stage_name, path )
    print(directory, name, file_path)

    VPCTemplate.set_class_variables(proj_long, proj_short, region, stage_name, template_output_dir=directory,)
    vpc = VPCTemplate("10.0.0.0/16")
    if 'prod' in stage_name.lower():
        vpc.add_prod_subnets()
    else:
        # Need 2 public subnets for the load balancer...
        vpc.add_subnets(azs=2)

    vpc.add_endpoint("S3")
    vpc.add_output("VPCID", reference_id=vpc.vpc_id.title)
    string_for_sn = ",".join(len(vpc.private_subnets) * ["${%s}"])
    vpc.add_output(
        "PrivateSubnetIds",
        # Jank construction of string... this needs to be better and added to the BaseClass somehow
        sub="${" + "},${".join([sn.logical_id for sn in vpc.private_subnets]) + "}",
    )
    vpc.add_output(
        "PublicSubnetIds",
        # Jank construction of string... this needs to be better and added to the BaseClass somehow
        sub="${" + "},${".join([sn.logical_id for sn in vpc.public_subnets]) + "}",
    )
    vpc.add_output("VPCCidrBlock", reference_id=vpc.vpc_id.title, attribute_id="CidrBlock")
    vpc.add_output("S3VPCEndpoint", reference_id=vpc.endpoints['S3'])
    vpc.save_template(name)
