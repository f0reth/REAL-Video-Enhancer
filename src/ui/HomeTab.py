from ..Util import openLink


class HomeTab:
    def __init__(self, parent):
        self.parent = parent
        self.QConnect()

    def QConnect(self):
        self.parent.githubBtn.clicked.connect(
            lambda: openLink("https://github.com/tntwise/REAL-Video-Enhancer")
        )
