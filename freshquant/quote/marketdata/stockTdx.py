# -*- coding: utf-8 -*-


class MarketData:
    def __init__(self):
        self.codeList = []

    def subscribe(self, code: str):
        if code not in self.codelist:
            self.codeList.append(code)

    def unsubscribe(self, code: str):
        self.codeList.remove(code)

    def run(self):
        pass


def main():
    MarketData().run()


if __name__ == "__main__":
    main()
