.. Versioning follows semantic versioning, see also
   https://semver.org/spec/v2.0.0.html. The most important bits are:
   * Update the major if you break the public API
   * Update the minor if you add new functionality
   * Update the patch if you fixed a bug

Changelog
=========

2.0.2 (2024-05-23)
------------------
- Included a py.typed file to indicate that the package is fully typed.

2.0.1 (2023-06-11)
------------------

- Fix exception when mixing patterns with prematchers and without prematchers.

2.0.0 (2023-03-08)
------------------

**Breaking change:** Prematchers now support non-ASCII characters. This will render all custom prematchers potentially invalid. **Please update your custom prematchers.**

Other changes:

- Add support for `.fullmatch`.
- Add a prematcher profiler.
- Up to 2x speedup in ``.search/.match/.fullmatch``.

1.0.0 (2022-05-16)
------------------

Initial release.
