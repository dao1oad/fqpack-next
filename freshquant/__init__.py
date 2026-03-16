import logging
import warnings

from freshquant.runtime.import_path import ensure_vendored_quantaxis_path
from freshquant.runtime.network import clear_proxy_env_for_current_process

clear_proxy_env_for_current_process()
ensure_vendored_quantaxis_path()

logging.disable(logging.INFO)
warnings.filterwarnings("ignore")
