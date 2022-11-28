import csv
import datetime
import json
import math
import threading
import time
from discord import Webhook
import numpy as np
from binance.client import Client
from unicorn_binance_websocket_api.manager import BinanceWebSocketApiManager
import sys

import config

client = Client(config.API_KEY, config.API_SECRET)
precision = 5
webhook = Webhook.from_url(config.WEBHOOK_URL)

# Exponentially Weighted Volatility
def ewma_volatility(source, period: float):
    final_values = []
    sqrt_annual = math.sqrt(365) * 100

    expo = period
    squared = np.power(source, 2)
    prev_vol = expo * squared[0] + (1.0 - expo) * squared[0]
    final_values.append(sqrt_annual * math.sqrt(prev_vol))

    for i in range(1, len(source)):
        prev_vol = expo * prev_vol + (1.0 - expo) * squared[i]
        final_values.append(sqrt_annual * math.sqrt(prev_vol))

    ewma_vol = final_values[-1]
    return ewma_vol


def place_buy_order(balance, price):
    quantity = balance / float(price)
    quantity = quantity * 0.99
    quantity = float(round(quantity, precision))

    order_placed = False
    order_response = {}
    total = 0.0
    while not order_placed:
        try:
            order_response = client.order_market_buy(symbol="BTCUSDT", quantity=quantity)
            order_placed = True
        except:
            quantity = quantity * 0.99
            quantity = float(round(quantity, precision))
            print("buy quantity:", quantity)
            if quantity < 0.00001:
                break

    for fill in order_response['fills']:
        total += (float(fill['price']) * float(fill['qty']))
        price = float(fill['price'])

    return total, price


def place_sell_order(quantity):
    order_placed = False
    total = 0.0
    order_response = {}
    while not order_placed:
        try:
            order_response = client.order_market_sell(symbol="BTCUSDT", quantity=quantity)
            order_placed = True
        except:
            quantity = quantity * 0.99
            quantity = float(round(quantity, precision))
            print("sell quantity:", quantity)
            if quantity < 0.00001:
                break

    price = 0.0
    for fill in order_response['fills']:
        total += (float(fill['price']) * float(fill['qty']))
        price = float(fill['price'])

    return total, price


def run_bot(binance_websocket_api_manager):
    lookback = config.lookback
    candles = client.get_historical_klines("BTCUSDT", Client.KLINE_INTERVAL_1MINUTE, "1 day ago UTC")
    candles_list = candles[-lookback-2:]
    closes = []
    for i in range(len(candles_list)-1):
        closes.append((candles_list[i][4]))
    bought = False

    csvfile = open('trades/1min_buys.csv', 'w', newline='')
    writer = csv.writer(csvfile, delimiter=',')

    spreads = []
    returns = []
    z = []
    first_time = False #used for testing
    buy_price = 0.0

    avg_spread = 0.0
    avg_return = 0.0
    trade_count = 0
    total_return = 0.0

    while True:

        if binance_websocket_api_manager.is_manager_stopping():
            exit(0)
        oldest_stream_data_from_stream_buffer = binance_websocket_api_manager.pop_stream_data_from_stream_buffer()
        if oldest_stream_data_from_stream_buffer is False:
            time.sleep(0.01)
        else:
            try:
                candlestick = json.loads(oldest_stream_data_from_stream_buffer)

                candle = candlestick['data']['k']
                is_candle_closed = candle['x']
                close = candle['c']

                if is_candle_closed or first_time:

                    account = client.get_account()["balances"]
                    buy_balance = float(account[11]['free'])
                    sell_balance = float(account[0]['free'])

                    closes.append(float(close))
                    first_time = False

                    if len(closes) > lookback+1:
                        closes = closes[1:]
                        #print(closes)
                        np_closes = np.array(closes, dtype=np.float64)
                        logr = np.diff(np.log(np_closes))
                        upR = np.copy(logr)
                        downR = np.copy(logr)
                        for i in range(len(upR)):
                            if upR[i] < 0:
                                upR[i] = 0
                            if downR[i] > 0:
                                downR[i] = 0
                        upSRC = ewma_volatility(upR[-lookback:], config.expo_rate)
                        downSRC = ewma_volatility(downR[-lookback:], config.expo_rate)
                        momentum = np.subtract(upSRC, downSRC)
                        z.append(momentum)
                        print(closes[-lookback:], z)
                        #print(z[-1])
                        # print(z, closes,logr)

                        if len(z) > 1:
                            if z[-1] > 0 and bought == False:
                                value, price = place_buy_order(balance=buy_balance, price=closes[-1])
                                x = datetime.datetime.now()
                                bought = True
                                buy_price = buy_balance

                                spread = abs(price - closes[-1])
                                spread_percent = spread / price * 100
                                spreads.append(spread_percent)

                                i = 0
                                avg_spread = 0
                                for spread in spreads:
                                    avg_spread += spread
                                    i += 1
                                avg_spread = avg_spread / i

                                writer.writerow(
                                    ["Buy", value, avg_spread, avg_return, x.strftime("%H:%M:%S:%f")])
                                print("Bought ",
                                      round(value, 3),
                                      " Dollars @ ",
                                      price,
                                      "     Total Return: ",
                                      round(total_return, 3),
                                      "     Average Spread: ",
                                      round(avg_spread, 3),
                                      "     Average Account Return: ",
                                      round(avg_return, 3),
                                      "             ",
                                      x.strftime("%H:%M:%S:%f"),
                                      sep="")
                                webhook_message = "<@133587276923011072>" \
                                                  + " Bought " \
                                                  + str(round(value, 3)) \
                                                  + " USD @ " \
                                                  + str(price) \
                                                  + ",  Total Return: " \
                                                  + str(round(total_return, 3)) \
                                                  + "%,  Avg Spread: " \
                                                  + str(round(avg_spread, 3)) \
                                                  + "%,  Avg Return Per Trade:  " \
                                                  + str(round(avg_return, 3)) \
                                                  + "%,           " \
                                                  + "Timestamp: " \
                                                  + x.strftime("%H:%M:%S:%f")
                                webhook.send(webhook_message)

                            if z[-1] < 0 and bought == True:
                                value, price = place_sell_order(quantity=sell_balance)
                                x = datetime.datetime.now()
                                bought = False
                                trade_count += 1

                                account = client.get_account()["balances"]
                                usdt_balance = float(account[11]['free'])

                                log_return = math.log(usdt_balance / buy_price) * 100
                                returns.append(log_return)

                                i = 0
                                avg_return = 0.0
                                for log_return in returns:
                                    avg_return += log_return
                                    i += 1
                                avg_return = avg_return / i
                                total_return = avg_return * trade_count

                                spread = abs(price - closes[-1])
                                spread_percent = spread / price * 100
                                spreads.append(spread_percent)

                                i = 0.0
                                avg_spread = 0.0
                                for spread in spreads:
                                    avg_spread += spread
                                    i += 1
                                avg_spread = avg_spread / i

                                writer.writerow(
                                    ["Sell", value, avg_spread, avg_return, x.strftime("%H:%M:%S:%f")])
                                print("Sold ",
                                      round(value, 3),
                                      " Dollars @ ",
                                      str(price),
                                      "     Total Return: ",
                                      round(total_return, 3),
                                      "     Average Spread: ",
                                      round(avg_spread, 3),
                                      "     Average Account Return: ",
                                      round(avg_return, 3),
                                      "             ",
                                      x.strftime("%H:%M:%S:%f"),
                                      sep="")
                                webhook_message = "<@133587276923011072>" \
                                                  + " Sold " \
                                                  + str(round(value, 3)) \
                                                  + " USD @ " \
                                                  + str(price) \
                                                  + ",  Total Return: " \
                                                  + str(round(total_return, 3)) \
                                                  + "%,  Avg Spread: " \
                                                  + str(round(avg_spread, 3)) \
                                                  + "%,  Avg Return Per Trade:  " \
                                                  + str(round(avg_return, 3)) \
                                                  + "%,           " \
                                                  + "Timestamp: " \
                                                  + x.strftime("%H:%M:%S:%f")
                                webhook.send(webhook_message)
                            z = z[1:]

            except Exception:
                # not able to process the data? write it back to the stream_buffer
                binance_websocket_api_manager.add_to_stream_buffer(oldest_stream_data_from_stream_buffer)


account = client.get_account()["balances"]
sell_balance = float(account[0]['free'])
if sell_balance > 0:
    place_sell_order(quantity=sell_balance)

binance_websocket_api_manager = BinanceWebSocketApiManager(exchange="binance.com")
worker_thread = threading.Thread(target=run_bot, args=(binance_websocket_api_manager,))
kline_stream_id = binance_websocket_api_manager.create_stream(['kline_1m'], ['btcusdt'])
worker_thread.start()

try:
    while True:
        time.sleep(60)

except KeyboardInterrupt:
    print("\nStopping ... just wait a few seconds!")
    binance_websocket_api_manager.stop_stream(kline_stream_id)
    binance_websocket_api_manager.stop_manager_with_all_streams()
