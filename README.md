### Türkiye Paketi

ERPNext v16 Türkiye muhasebe ve vergi paketi (kapanış, KDV, tevkifat, beyanname ayrımları, e-belge arayüzü)

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI (run from your bench directory):

```bash
bench get-app https://github.com/Framras/erpnext-tr.git --branch develop
bench install-app erpnext_tr
```

### Contributing

This app uses `pre-commit` for basic syntax and safety checks (merge conflicts, AST, JSON/YAML/TOML, debug statements, trailing whitespace). Formatting and linting (ruff, eslint, prettier) come from the Frappe/ERPNext bench environment—do not duplicate them here. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/erpnext_tr
pre-commit install
```

### License

mit
