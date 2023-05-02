import click


@click.group()
def cli():
    pass


@cli.command()
def hello():
    print("Hello")


if __name__ == "__main__":
    cli()
