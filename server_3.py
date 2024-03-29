from flask import Flask
from flask import render_template
from flask import request
from flask import send_from_directory
import datetime
from pymongo import MongoClient
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import random
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor

app = Flask(__name__)

client = MongoClient()
db = client.data602

currencies = {}
for x in db.balance.find():
    currencies[x['currency']] = x['qty']

def api_query(method, **args):
    urlparams = '&'.join(['%s=%s' % (key, args[key]) for key in args])
    page = requests.get('https://min-api.cryptocompare.com/data/%s?%s' % (method, urlparams))
    return page.json()

def get_histoday(cur1, cur2, limit):
    data = api_query('histoday', tsym=cur1, fsym=cur2, limit=limit)['Data']
    df = pd.DataFrame(data)
    df['timestamp'] = [datetime.datetime.fromtimestamp(d) for d in df.time]
    return df

def get_histoday20d(cur1, cur2):
    data = api_query('histoday', tsym=cur1, fsym=cur2, limit=19)['Data']
    return pd.DataFrame({'price': [x['close'] for x in data]})

def get_price(cur1, cur2):
    return api_query('price', fsym=cur1, tsyms=cur2)[cur2]

def get_average24h(cur1, cur2):
    return api_query('dayAvg', fsym=cur1, tsym=cur2)[cur2]

def get_stat24h(cur1, cur2):
    data = api_query('histoday', fsym=cur1, tsym=cur2, limit=1)['Data']
    return (data[1]['low'], data[1]['high'])

def get_sd24h(cur1, cur2):
    n = 24
    sum = 0
    data = api_query('histohour', fsym=cur1, tsym=cur2, limit=n-1)['Data']
    for item in data:
        sum += item['close']
    avg_price = sum / n
    sum = 0
    for item in data:
        sum += (item['close'] - avg_price) ** 2
    return (sum / n) ** 0.5

def get_data(cur):
    data = api_query('histoday', fsym=cur, tsym='USD', limit=730)['Data']
    features = {key: [] for key in data[0].keys()}
    for i in range(len(data) - 1):
        for key in data[i]:
            features[key].append(data[i][key])

    labels = np.array([data[i]['close'] for i in range(len(data) - 1)])
    features = np.array(pd.DataFrame(features))
    test = data[len(data) - 1]
    return (features, labels, test)

def gradient_boosting(data):
    features, labels, test = data

    gb = GradientBoostingRegressor(n_estimators = 1000, random_state = 42)
    gb.fit(features, labels)

    return gb.predict(np.array(pd.DataFrame([test])))[0]

def random_forest(data):
    features, labels, test = data

    rf = RandomForestRegressor(n_estimators = 1000, random_state = 42)
    rf.fit(features, labels)

    return rf.predict(np.array(pd.DataFrame([test])))[0]


@app.route('/')
def index():
    trades = []
    for cur1 in currencies:
        if currencies[cur1] > 0:
            for cur2 in currencies:
                if cur1 != cur2:
                    trades.append({
                      'cur1': cur1,
                      'cur2': cur2
                    })
    blotter = [x for x in db.transactions.find()]

    cur = {}
    for c in currencies:
        cur[c] = {
          'qty': currencies[c],
          'bought': 0,
          'sum_bought': 0,
          'sold': 0,
          'sum_sold': 0,
          'last_price': 0,
          'rpl': 0,
          'upl': 0,
          'wap': 0,
          'vwap': {},
          'pf': {},
          'balance': 0,
          'allocation_by_shares': 0,
          'allocation_by_dollars': 0,
          'total_pl': 0,
          'prediction1': None,
          'prediction2': None,
          'time': [],
          'rate': []
        }
    
    cash_by_days = {}
    for ts in blotter:
        cur[ts['to']]['bought'] += float(ts['in'])
        cur[ts['to']]['sum_bought'] += float(ts['USD_sum'])
        cur[ts['to']]['last_price'] = float(ts['USD_sum']) / float(ts['in'])
        cur[ts['from']]['sold'] += float(ts['out'])
        cur[ts['from']]['sum_sold'] += float(ts['USD_sum'])
        cur[ts['to']]['time'].append(ts['date'])
        cur[ts['to']]['rate'].append(ts['rate'])
        
        date = str(ts['date'].date())
        cash_by_days[date] = ts['cash']
        
        if ts['to'] != 'USD':
            o = cur[ts['to']]['vwap'].get(date, {
              'bought': 0,
              'sum_bought': 0,
              'wap': 0
            })
            o['bought'] += float(ts['in'])
            o['sum_bought'] += float(ts['USD_sum'])
            cur[ts['to']]['vwap'][date] = o

            cur[ts['to']]['balance'] += float(ts['in'])
            cur[ts['to']]['pf'][date] = cur[ts['to']]['balance']
            if ts['from'] != 'USD':
                cur[ts['from']]['balance'] -= float(ts['out'])
                cur[ts['from']]['pf'][date] = cur[ts['from']]['balance']

    qty_all = 0
    sum_usd = 0
    for c in cur:
        if c != 'USD':
            cur[c]['wap'] = cur[c]['sum_bought'] / cur[c]['bought'] if cur[c]['bought'] > 0 else 0
            cur[c]['rpl'] = cur[c]['sum_sold'] - cur[c]['wap'] * cur[c]['sold']
            cur[c]['upl'] = (cur[c]['last_price'] - cur[c]['wap']) * cur[c]['qty']
            cur[c]['total_pl'] = cur[c]['rpl'] + cur[c]['upl']
            for day in cur[c]['pf']:
                cur[c]['pf'][day] *= cur[c]['last_price']
            
            for date in cur[c]['vwap']:
                o = cur[c]['vwap'][date]
                
                cur[c]['vwap'][date] = o['sum_bought'] / o['bought']

            qty_all += cur[c]['qty']
            sum_usd += cur[c]['qty'] * cur[c]['wap']

    for c in cur:
        if c != 'USD':
            cur[c]['allocation_by_shares'] = cur[c]['qty'] / qty_all * 100 if qty_all > 0 else 0
            cur[c]['allocation_by_dollars'] = cur[c]['qty'] * cur[c]['wap'] / sum_usd * 100 if sum_usd > 0 else 0
  
    pl = []

    data_btc = get_data('BTC')
    data_eth = get_data('ETH')

    cur['BTC']['prediction1'] = random_forest(data_btc)
    cur['ETH']['prediction1'] = random_forest(data_eth)
    
    cur['BTC']['prediction2'] = gradient_boosting(data_btc)
    cur['ETH']['prediction2'] = gradient_boosting(data_eth)
    
    for c in cur:
        pl.append({
            'currency': c,
            'qty': '%.2f' % (cur[c]['qty']),
            'upl': '%.2f' % (cur[c]['upl']),
            'rpl': '%.2f' % (cur[c]['rpl']),
            'wap': '%.2f' % (cur[c]['wap']),
            'market': '%.2f' % (cur[c]['last_price']),
            'allocation_by_shares': '%.2f' % (cur[c]['allocation_by_shares']),
            'allocation_by_dollars': '%.2f' % (cur[c]['allocation_by_dollars']),
            'total_pl': '%.2f' % (cur[c]['total_pl']),
            'prediction1': ('%.2f' % (cur[c]['prediction1'])) if cur[c]['prediction1'] != None else '-',
            'prediction2': ('%.2f' % (cur[c]['prediction2'])) if cur[c]['prediction2'] != None else '-'
        })

    #cash-time
    plt.plot(list(cash_by_days.keys()), list(cash_by_days.values()))
    plt.xticks(rotation=45)
    plt.yticks(rotation=45)
    plt.title("Cash time")
    plt.rc('xtick', labelsize=6)
    plt.rc('ytick', labelsize=8)
    plt.savefig('img/cash_time.png')
    plt.close()
    
    #portfolio
    for c in cur:
        if c != 'USD':
            plt.plot(list(cur[c]['pf'].keys()), list(cur[c]['pf'].values()))

    plt.xticks(rotation=45)
    plt.yticks(rotation=45)
    plt.title("Portfolio")
    plt.rc('xtick', labelsize=6) 
    plt.rc('ytick', labelsize=8)
    plt.savefig('img/portfolio.png')
    plt.close()

    #vwap
    for c in cur:
        if c != 'USD':
            plt.plot(list(cur[c]['vwap'].keys()), list(cur[c]['vwap'].values()))

    plt.xticks(rotation=45)
    plt.yticks(rotation=45)
    plt.title("VWAP")
    plt.rc('xtick', labelsize=6) 
    plt.rc('ytick', labelsize=8)
    plt.savefig('img/vwap.png')
    plt.close()
    
    #exec-price
    for c in currencies:
        plt.plot(list(cur[c]['time']), list(cur[c]['rate']))
    plt.xticks(rotation=45)
    plt.yticks(rotation=45)
    plt.title("Executed price")
    plt.rc('xtick', labelsize=6) 
    plt.rc('ytick', labelsize=8)
    plt.savefig('img/exec_price.png')
    plt.close()

    return render_template("index.html",
      trades = trades,
      blotter = blotter,
      pl = pl,
      r = random.random()
    )

@app.route('/trade')
def trade():
    cur1 = request.args.get('cur1')
    cur2 = request.args.get('cur2')
    
    df = get_histoday(cur1, cur2, 100)
    plt.plot(df.timestamp, df.close)
    plt.xticks(rotation=90)
    plt.title("100 days history")
    plt.savefig('img/history_%s_%s.png' % (cur1, cur2))
    plt.close()

    px = pd.DataFrame(get_histoday20d(cur1, cur2))
    px['20d rm'] = pd.rolling_mean(px['price'], window=19)
    plt.plot(px)
    plt.title("20 days moving average")
    plt.savefig('img/moving_avg_%s_%s.png' % (cur1, cur2))
    plt.close()

    min, max = get_stat24h(cur2, cur1)
    stat = {
      'Max (24h)': '%f' % (max),
      'Min (24h)': '%f' % (min),
      'Average (24h)': '%f' % (get_average24h(cur2, cur1)),
      'Standart deviation (24h)': '%f' % (get_sd24h(cur2, cur1))
    }

    price = get_price(cur2, cur1)

    return render_template('trade.html',
      cur1 = cur1,
      cur2 = cur2,
      price = price,
      stat = stat
    )

@app.route('/deal')
def deal():
    cur1 = request.args.get('cur1')
    cur2 = request.args.get('cur2')
    cur2_qty = float(request.args.get('qty'))
    price = get_price(cur2, cur1)
    cur1_qty = cur2_qty * price
    if cur1_qty > currencies[cur1]:
        text = "Not enough money"
    else:
        currencies[cur1] -= cur1_qty
        currencies[cur2] += cur2_qty
        db.balance.update(
          {'currency': cur1},
          {'currency': cur1, 'qty': currencies[cur1]}
        )
        db.balance.update(
          {'currency': cur2},
          {'currency': cur2, 'qty': currencies[cur2]}
        )
        db.transactions.insert_one({
            "date": datetime.datetime.now(),
            "from": cur1,
            "to": cur2,
            "rate": price,
            "out": cur1_qty,
            "in": cur2_qty,
            "cash": "%.2f" % (currencies['USD']),
            "USD_sum": "%.2f" % (get_price(cur2, 'USD') * cur2_qty)
        })
        text = "Thank you! Your transaction went through. Ramaining balance is %f" % currencies['USD']
    return render_template("deal.html",
      text = text,
      cur1 = cur1,
      cur2 = cur2
    )

@app.route('/img/<path:path>')
def send_img(path):
    return send_from_directory('img', path)
    
app.run(host='0.0.0.0', port=5000)
