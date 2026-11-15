### Türkiye Paketi

ERPNext v16 Türkiye muhasebe ve vergi paketi (kapanış, KDV, tevkifat, beyanname ayrımları, e-belge arayüzü)

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI (run from your bench directory):

```bash
bench get-app https://github.com/Framras/erpnext-tr.git --branch develop
bench install-app erpnext_tr
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/erpnext_tr
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
