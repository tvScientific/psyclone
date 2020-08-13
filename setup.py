from setuptools import setup
import os

with open('README.md') as f:
    long_description = f.read()

with open(os.path.join(os.path.split(__file__)[0], 'requirements.txt')) as f:
    reqs = f.readlines()

setup(
    name='psyclone',
    version="0.1",
    description='A pip selection of tools for easier processing of data using Pandas and AWS',
    long_description=long_description,
    long_description_content_type="text/markdown",
    url='https://bitbucket.org/dativa4data/psyclone/',
    author='Deductive',
    author_email='hello@deductive.com',
    zip_safe=False,
    packages=['dashboards'],
    include_package_data=True,
    setup_requires=[
        'setuptools>=41.0.1',
        'wheel>=0.33.4',
        'numpy>=1.13.3'
    ],
    install_requires=[reqs]
)
