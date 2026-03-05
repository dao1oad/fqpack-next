import argparse
from freshquant.preset.index import init_indexes
from freshquant.preset.params import init_param_dict
from freshquant.preset.strategies import init_strategy_dict

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--quiet', action='store_true', help='不执行任何操作直接退出')
    args = parser.parse_args()
    init_indexes()
    init_param_dict(args.quiet)
    init_strategy_dict()
