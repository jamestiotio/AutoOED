from utils import set_environment
from system.scientist.controller.team import ScientistController


def main():
    set_environment()
    ScientistController().run()


if __name__ == '__main__':
    main()