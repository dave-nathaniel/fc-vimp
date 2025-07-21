import os

def env_variables(request):
    """
        Context processor that returns selected environment variables.
    """
    keys = [
        'SAP_URL',
    ]
    env_vars = {key: os.environ.get(key) for key in keys}
    return {'env': env_vars}
