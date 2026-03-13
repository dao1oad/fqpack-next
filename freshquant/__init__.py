import logging
import warnings

from freshquant.runtime.import_path import ensure_vendored_quantaxis_path

ensure_vendored_quantaxis_path()

logging.disable(logging.INFO)
warnings.filterwarnings("ignore")
