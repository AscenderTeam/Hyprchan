from ascender.core.applications.create_application import createApplication

from hyprchan.bootstrap import appBootstrap

app = createApplication(config=appBootstrap)


def launch() -> None:
    app.launch()


if __name__ == "__main__":
    launch()
