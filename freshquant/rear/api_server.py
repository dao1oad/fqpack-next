import argparse
from flask import Flask
from gevent.pywsgi import WSGIServer
from freshquant.rear.future.routes import future_bp
from freshquant.rear.stock.routes import stock_bp
from freshquant.rear.general.routes import general_bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(future_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(general_bp)
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
