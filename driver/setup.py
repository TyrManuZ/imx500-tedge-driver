from setuptools import setup, find_packages

setup(
    name='imx500_driver',
    version='0.0.1',
    packages=find_packages(),
    install_requires=[
        'requests',
        'paho-mqtt',
        'Flask',
        'flatbuffers',
        'numpy'
    ],
    entry_points={
        'console_scripts': [
            'imx500_driver=imx500_driver.server:main',
        ],
    },
    author='Tobias Sommer',
    author_email='tobias.sommer@cumulocity.com',
    description='A brief description of your project',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/yourusername/my_project',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)