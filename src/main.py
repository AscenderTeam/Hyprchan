from bootstrap import appBootstrap
from ascender.core._builder.build import build
from ascender.core.applications.create_application import createApplication
app = createApplication(config=appBootstrap)


if __name__ == "__main__":
    app.launch()