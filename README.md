
# lmk

[![Build Status](https://travis-ci.org/cfeenstra67/lmk.svg?branch=master)](https://travis-ci.org/cfeenstra67/lmk)
[![codecov](https://codecov.io/gh/cfeenstra67/lmk/branch/master/graph/badge.svg)](https://codecov.io/gh/cfeenstra67/lmk)


A Custom Jupyter Widget Library

## Installation

You can install using `pip`:

```bash
pip install lmk
```

If you are using Jupyter Notebook 5.2 or earlier, you may also need to enable
the nbextension:
```bash
jupyter nbextension enable --py [--sys-prefix|--user|--system] lmk
```

## Development Installation

Create a dev environment:
```bash
conda create -n lmk-dev -c conda-forge nodejs yarn python jupyterlab
conda activate lmk-dev
```

Install the python. This will also build the TS package.
```bash
pip install -e ".[test, examples]"
```

When developing your extensions, you need to manually enable your extensions with the
notebook / lab frontend. For lab, this is done by the command:

```
jupyter labextension develop --overwrite .
yarn run build
```

For classic notebook, you need to run:

```
jupyter nbextension install --sys-prefix --symlink --overwrite --py lmk
jupyter nbextension enable --sys-prefix --py lmk
```

Note that the `--symlink` flag doesn't work on Windows, so you will here have to run
the `install` command every time that you rebuild your extension. For certain installations
you might also need another flag instead of `--sys-prefix`, but we won't cover the meaning
of those flags here.

### How to see your changes
#### Typescript:
If you use JupyterLab to develop then you can watch the source directory and run JupyterLab at the same time in different
terminals to watch for changes in the extension's source and automatically rebuild the widget.

```bash
# Watch the source directory in one terminal, automatically rebuilding when needed
yarn run watch
# Run JupyterLab in another terminal
jupyter lab
```

After a change wait for the build to finish and then refresh your browser and the changes should take effect.

#### Python:
If you make a change to the python code then you will need to restart the notebook kernel to have it take effect.

## Updating the version

To update the version, install tbump and use it to bump the version.
By default it will also create a tag.

```bash
pip install tbump
tbump <new-version>
```

## Notes

Juypter extension doesn't work in vscode, would need to create a vscode extension for that; see https://github.com/microsoft/vscode-jupyter#notebook-support
- It seems like vscode's notebook support may not be implemented correctly/doesn't look for modules in the same way as jupyter, because it is working on both jupyter notebook classic and jupyter lab, and in theory it should not be a problem to find the JS for the extension. Experiment

- Makes an ascii-friendly interactive version for channels more attractive
