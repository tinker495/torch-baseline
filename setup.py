from setuptools import setup
setup(
    name='torch_baselines',
    version='0.0.1',
    packages=['torch_baselines'],
    install_requires=[
        'requests',
        'mlagents_envs==0.27.0',
        'gym',
        'box2d',
        'box2d-py',
        'torch',
        'numpy',
        'importlib; python_version >= "3.5"',
        'git+https://github.com/kenjyoung/MinAtar.git#egg=Minatar'
    ],
)