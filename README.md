# Binance Real Time Trading Bot

This software receives live Crypto pricing data from Binance, calculates custom momentum indicator values, then places buy and sell orders when appropriate.

You can receive notifications each time an order is placed via Discord webhook.

### Getting Started

Install the python dependencies using:
```pip install -r requirements.txt```


### Using the App

Insert your configuration parameters in ```config.py```

Use the command: ```python .\ewma_bot.py```

Trade data is stored in ```trades``` directory