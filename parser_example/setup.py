from setuptools import setup, find_packages

setup(
    name='imx500_parser',
    version='0.0.1',
    packages=find_packages(),
    install_requires=[
        'paho-mqtt'
    ],
    entry_points={
        'console_scripts': [
            'imx500_parser=imx500_parser.parser:main',
        ],
    },
    author='Tobias Sommer',
    author_email='tobias.sommer@cumulocity.com',
    description='A brief description of your project',
    url='https://github.com/yourusername/my_project',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)