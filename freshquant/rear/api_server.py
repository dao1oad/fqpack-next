import argparse

from flask import Flask
from gevent.pywsgi import WSGIServer


def create_app():
    from importlib import import_module

    app = Flask(__name__)
    app.register_blueprint(import_module("freshquant.rear.future.routes").future_bp)
    app.register_blueprint(import_module("freshquant.rear.stock.routes").stock_bp)
    app.register_blueprint(import_module("freshquant.rear.general.routes").general_bp)
    app.register_blueprint(import_module("freshquant.rear.gantt.routes").gantt_bp)
    app.register_blueprint(import_module("freshquant.rear.order.routes").order_bp)
    app.register_blueprint(import_module("freshquant.rear.tpsl.routes").tpsl_bp)
    return app


def run(port):
    app = create_app()
    http_serv = WSGIServer(("0.0.0.0", port), app)
    http_serv.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    run(args.port)
