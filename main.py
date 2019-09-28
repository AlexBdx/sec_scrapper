#!/usr/bin/env python
# coding: utf-8

# # Configuration

# ## Packages to import

# In[1]:


def run_from_ipython():
    try:
        __IPYTHON__
        return True
    except NameError:
        return False


# In[2]:


if run_from_ipython():
    get_ipython().run_line_magic('load_ext', 'autoreload')
    get_ipython().run_line_magic('autoreload', '2')
    get_ipython().run_line_magic('matplotlib', 'notebook')

from insight import *

import glob
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
plt.ioff()

import os
import csv
from datetime import datetime
import re
from tqdm import tqdm
import multiprocessing as mp
from collections import OrderedDict
import time
import pandas as pd
import argparse


# ### Set the nb of processes to use based on cmd line arguments/setting

# In[3]:


if run_from_ipython():
    nb_processes_requested = mp.cpu_count()  # From IPython, fixed setting
else:
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--processes", type=int, default=1, help="Number of processes launched to process the reports.")
    args = vars(ap.parse_args())
    nb_processes_requested = args["processes"]
    if not 1 <= nb_processes_requested <= mp.cpu_count():
        raise ValueError('[ERROR] Number of processes requested is incorrect.                         \n{} CPUs are available on this machine, please select a number of processes between 1 and {}'
                         .format(mp.cpu_count()))


# ## Settings dictionary

# In[4]:


home = os.path.expanduser("~")
_s = {
    'path_stage_1_data': os.path.join(home, 'Desktop/filtered_text_data/nd_data/'),
    'path_stock_database': os.path.join(home, 'Desktop/Insight project/Database/Ticker_stock_price.csv'),
    'path_stock_indexes': os.path.join(home, 'Desktop/Insight project/Database/Indexes/'),
    'path_cik_ticker_lookup': os.path.join(home, 'Desktop/Insight project/Database/cik_ticker.csv'),
    'path_master_dictionary': os.path.join(home, 'Desktop/Insight project/Database/LoughranMcDonald_MasterDictionary_2018.csv'),
    'path_dump_crsp': os.path.join(home, 'Desktop/Insight project/Database/dump_crsp_merged.txt'),
    'path_output_folder': os.path.join(home, 'Desktop/Insight project/Outputs'),
    'metrics': ['diff_jaccard', 'diff_cosine_tf', 'diff_cosine_tf_idf', 'diff_minEdit', 'diff_simple', 'sing_LoughranMcDonald'],
    'differentiation_mode': 'intersection',
    'time_range': [(2010, 1), (2012, 4)],
    'bin_count': 5,
    'report_type': ['10-K', '10-Q'],
    'sections_to_parse_10k': [],
    'sections_to_parse_10q': [],
    'type_daily_price': 'closing'
}


# In[5]:


_s['pf_init_value'] = 1000000
_s['epsilon'] = 0.0001  # Rounding error
# Calculated settings
_s['list_qtr'] = qtrs.create_qtr_list(_s['time_range'])

if _s['bin_count'] == 5:
    _s['bin_labels'] = ['Q'+str(n) for n in range(1, _s['bin_count']+1)]
elif _s['bin_count'] == 10:
    _s['bin_labels'] = ['D'+str(n) for n in range(1, _s['bin_count']+1)]
else:
    raise ValueError('[ERROR] This type of bin has not been implemented yet.')

# Reports considered to calculate the differences
if _s['differentiation_mode'] == 'intersection':
    _s['lag'] = 1
    _s['sections_to_parse_10k'] = ['1a', '3', '7', '7a', '9a']
    _s['sections_to_parse_10q'] = ['_i_2', '_i_3', '_i_4', 'ii_1', 'ii_1a']
elif _s['differentiation_mode'] == 'yearly':
    _s['lag'] = 4
    _s['sections_to_parse_10k'] = []
    _s['sections_to_parse_10q'] = []

_s['intersection_table'] = {
        '10-K': ['1a', '3', '7', '7a', '9a'],
        '10-Q': ['ii_1a', 'ii_1', '_i_2', '_i_3', '_i_4']
}  # Exhibits are not taken into account
_s['straight_table'] = {
    '10-K': ['1', '1a', '1b', '2', '3', '4', '5', '6', '7', '7a', '8', '9', '9a', '9b', '10', '11', '12', '13', '14', '15'],
    '10-Q': ['_i_1', '_i_2', '_i_3', '_i_4', 'ii_1', 'ii_1a', 'ii_2', 'ii_3', 'ii_4', 'ii_5', 'ii_6']
}


# In[6]:


# Transfer s to a read only dict
read_only_dict = pre_processing.ReadOnlyDict()
for key in _s:  # Brute force copy
    read_only_dict[key] = _s[key]
s = read_only_dict  # Copy back
s.set_read_state(read_only=True)  # Set as read only


# # Load external tables

# ## Extract the list of CIK for which we have complete data

# The main problem in our case is that we have 3 different database to play with:
# 1. The SEC provides information based on the CIK of the entity
# 2. Given that the CIK is used by no one else, we use a lookup table to transform that into tickers. But we do not have all the correspondances, so the list of useful CIK is shrunk.
# 3. Finally, we only have stock prices for so many tickers. So that shrinks the CIK list even further.
# 
# We end up with a reduced list of CIK that we can play with.

# ### Find all the unique CIK from the SEC filings

# In[7]:


cik_path = pre_processing.load_cik_path(s)


# ### Get the largest {CIK: ticker} possible given our lookup table

# In[8]:


lookup = pre_processing.load_lookup(s)
print("[INFO] Loaded {:,} CIK/Tickers correspondances.".format(len(lookup)))


# In[9]:


cik_path, lookup = pre_processing.intersection_sec_lookup(cik_path, lookup)
print("[INFO] Intersected SEC & lookup.")
print("cik_path: {:,} CIK | lookup: {:,} CIK"
      .format(len(cik_path), len(lookup)))


# ### Load stock data and drop all CIKs for which we don't have data

# In[10]:


# Load all stock prices
stock_data = pre_processing.load_stock_data(s)


# In[11]:


lookup, stock_data = pre_processing.intersection_lookup_stock(lookup, stock_data)
print("[INFO] Intersected lookup & stock data.")
print("lookup: {:,} tickers | stock_data: {:,} tickers"
      .format(len(lookup.values()), len(stock_data)))


# ### Load stock indexes - will serve as benchmark later on

# In[12]:


index_data = pre_processing.load_index_data(s)
print("[INFO] Loaded the following index data:", list(index_data.keys()))


# ## Back propagate these intersection all the way to cik_path

# Technically, we have just done it for lookup. So we only need to re-run an intersection for lookup and sec.

# In[13]:


cik_path, lookup = pre_processing.intersection_sec_lookup(cik_path, lookup)
print("[INFO] Intersected SEC & lookup.")
print("cik_path: {:,} CIK | lookup: {:,} CIK"
      .format(len(cik_path), len(lookup)))


# ## Sanity check

# At this point, cik_path and lookup should have the same number of keys as the CIK is unique in the path database.
# 
# However, multiple CIK can redirect to the same ticker if the company changed its ticker over time. That should be a very limited amount of cases though.

# In[14]:


assert cik_path.keys() == lookup.keys()
assert len(set(lookup.values())) == len(set(stock_data.keys()))


# At that point, we have a {CIK: ticker} for which the stock is known, which will enable comparison and all down the road.

# ## Review all CIKs: make sure there is only one submission per quarter

# In this section, the goal is to build a list of CIK that will successfully be parsed for the time_range considered.
# It should be trivial for a vast majority of the CIK, but ideally there should be only one document per quarter for each CIK from the moment they are listed to the moment they are delisted.

# In[15]:


# Create the list of quarters to consider
cik_path = pre_processing.review_cik_publications(cik_path, s)
print("[INFO] Removed all the CIK that did not have one report per quarter.")
print("cik_dict: {:,} CIK".format(len(cik_path)))


# In[16]:


print("[INFO] We are left with {:,} CIKs that meet our requirements:".format(len(cik_path)))
print("- The ticker can be looked up in the CIK/ticker tabke")
print("- The stock data is available for that ticker")
print("- There is one and only one report per quarter")


# In[17]:


"""
# [USER SETTINGS]
example = 'apple'  # Debug
# Examples of companies
example_companies = {
    'apple': ['AAPL', 320193],
    'baxter': ['BAX', 10456],
    'facebook': ['FB', 1326801],
    'google': ['GOOGL', 1652044],
    'microsoft': ['MSFT', 789019],
    'amazon': ['AMZN', 1018724],
    'johnson': ['JNJ', 200406],
    'jpmorgan': ['JPM', 19617]
}

# [DEBUG]: isolate a subset of companies
company = 'apple'
cik_path = {
    example_companies['apple'][1]: cik_path[example_companies['apple'][1]],
    example_companies['microsoft'][1]: cik_path[example_companies['microsoft'][1]],
    example_companies['jpmorgan'][1]: cik_path[example_companies['jpmorgan'][1]],
    example_companies['amazon'][1]: cik_path[example_companies['amazon'][1]],
    example_companies['johnson'][1]: cik_path[example_companies['johnson'][1]],
    
}
cik_path.keys()
"""


# # Parse files

# Now we have a list of CIK that should make it until the end. It is time to open the relevant reports and start parsing. This step takes a lot of time and can get arbitrarily long as the metrics get fancier.
# 
# You do not want to keep in RAM all the parsed data. However, there are only ~100 quarters for which we have data and the stage 2 files are no more than 1 Mb in size (Apple seems to top out at ~ 325 kb). So 100 Mb per core + others, that's definitely doable. More cores will use more RAM, but the usage remains reasonable.
# 
# We use multiprocessing to go through N CIK at once but a single core is dedicated to going through a given CIK for the specified time_range. Such a core can be running for a while if the company has been in business for the whole time_range and publish a lot of text data in its 10-K.

# In[18]:


# Processing the reports will be done in parrallel in a random order
cik_scores = {k: 0 for k in cik_path.keys()}  # Organized by ticker
#debug = [[k, v, {**s}] for k, v in cik_path.items() if k==98338]  # settings are cast to dict for pickling
debug = [[k, v, {**s}] for k, v in cik_path.items()]  # settings are cast to dict for pickling

data_to_process = debug[:100]  # Debug
#print(data_to_process)
#result = process_cik(data_to_process[0])
#cik_perf[result[0]] = result[1]
#print(cik_perf)
#assert 0
processing_stats = [0, 0, 0, 0, 0, 0]
#qtr_metric_result = {key: [] for key in s['list_qtr']}
    
with mp.Pool(processes=nb_processes_requested) as p:
#with mp.Pool(processes=min(mp.cpu_count(), 1)) as p:
    print("[INFO] Starting a pool of {} workers".format(nb_processes_requested))

    with tqdm(total=len(data_to_process)) as pbar:
        for i, value in tqdm(enumerate(p.imap_unordered(processing.process_cik, data_to_process))):
            pbar.update()
            #qtr = list_qtr[i]
            # Each quarter gets a few metrics
            if value[1] == {}:
                # The parsing failed
                del cik_scores[value[0]]
            else:
                cik_scores[value[0]] = value[1]
            processing_stats[value[2]] += 1
           
        #qtr_metric_result[value['0']['qtr']] = value
print("[INFO] {} CIK failed to be processed.".format(sum(processing_stats[1:])))
print("Detailed stats:", processing_stats)


# # Post-processing - Welcome to the gettho

# ## Flip the result dictionary to present a per qtr view

# In[19]:


# Reorganize the dict to display the data per quarter instead
qtr_scores = {qtr: {} for qtr in s['list_qtr']}
for c in cik_path.keys():
    if c in cik_scores.keys():
        if cik_scores[c] == 0:
            del cik_scores[c]

for cik in tqdm(cik_scores):
    for qtr in cik_scores[cik]:
        qtr_scores[qtr][cik] = cik_scores[cik][qtr]

assert list(qtr_scores.keys()) == s['list_qtr']


# ## Create a separate dictionary for each metric

# In[20]:


# Create the new empty master dictionary
master_dict = {m: 0 for m in s['metrics']}
for m in s['metrics']:
    master_dict[m] = {qtr: 0 for qtr in s['list_qtr']}
# master_dict


# In[21]:


# Populate it
for m in s['metrics']:
    for qtr in s['list_qtr']:
        #master_dict[m][qtr] = {cik: qtr_scores[qtr][cik][m] for cik in qtr_scores[qtr].keys()}
        master_dict[m][qtr] = [(cik, qtr_scores[qtr][cik][m]) for cik in qtr_scores[qtr].keys()]


# In[22]:


# Display the length for all qtr
for qtr in s['list_qtr']:
    print("qtr: {} length: {}".format(qtr, len(master_dict[s['metrics'][0]][qtr])))


# ## For each metric, split each qtr into 5 quintiles
# 
# For each metric and for each quarter, make quintiles containing all the (cik, score) tuples. 
# 
# Now at this point the portfolio is not balanced, it is just the list of companies we would like to invest in. We need to weigh each investment by the relative market cap. 

# In[23]:


# Populate it
# The two zeros are respectively nb shares unbalanced & balanced
for m in s['metrics']:
    for qtr in s['list_qtr']:
        #master_dict[m][qtr] = {cik: qtr_scores[qtr][cik][m] for cik in qtr_scores[qtr].keys()}
        master_dict[m][qtr] = [[cik, qtr_scores[qtr][cik][m], 0, 0] for cik in qtr_scores[qtr].keys()]
# master_dict


# In[24]:


# Reorganize each quarter 
for m in s['metrics'][:-1]:
    for qtr in s['list_qtr'][s['lag']:]:  # There cannot be a report for the first few qtr
        #print(master_dict[m][qtr])
        try:
            master_dict[m][qtr] = post_processing.make_quintiles(master_dict[m][qtr], s)
        except:
            #print(master_dict[m][qtr])
            raise
        assert len(master_dict[m][qtr].keys()) == 5


# In[25]:


pf_scores = {m: 0 for m in s['metrics'][:-1]}
for m in s['metrics']:
    pf_scores[m] = {q: {qtr: 0 for qtr in s['list_qtr'][s['lag']:]} for q in s['bin_labels']}


# In[26]:


for m in s['metrics'][:-1]:
    for mod_bin in s['bin_labels']:
        for qtr in s['list_qtr'][s['lag']:]:
            pf_scores[m][mod_bin][qtr] = master_dict[m][qtr][mod_bin]
# pf_scores['diff_jaccard']['Q1']


# In[27]:


# del master_dict


# In[28]:


def dump_master_dict(path, master_dict):
    # path = '/home/alex/Desktop/Insight project/Database/dump_master_dict.csv'
    with open(path, 'w') as f:
        out = csv.writer(f, delimiter=';')
        header = ['METRIC', 'QUARTER', 'QUINTILE', 'CIK', 'SCORE']
        out.writerow(header)
        
        # Main writing loop
        for m in tqdm(s['metrics'][:-1]):
            for qtr in s['list_qtr'][s['lag']:]:
                for l in s['bin_labels']:
                    for entry in master_dict[m][qtr][l]:
                        out.writerow([m, qtr, l, entry[0], entry[1]])


# In[29]:


path = '/home/alex/Desktop/Insight project/Database/dump_master_dict.csv'
dump_master_dict(path, master_dict)


# In[30]:


master_dict['diff_jaccard'][(2010, 2)].keys()


# ## Create a virtual portfolio
# 
# Re-calculate the value of the portfolio at the end of each quarter.

# ### Remove all the CIK for which we do not have stick data for this time period

# In[31]:


pf_scores = post_processing.remove_cik_without_price(pf_scores, lookup, stock_data, s)


# In[32]:


# Create the new empty master dictionary
tax_rate = 0.005
pf_values = {m: 0 for m in s['metrics'][:-1]}
for m in s['metrics'][:-1]:
    pf_values[m] = {q: {qtr: [0, tax_rate, 0] for qtr in s['list_qtr'][1:]} for q in s['bin_labels']}


# ## Initialize the portfolio with an equal amount for all bins

# In[33]:


for m in s['metrics'][:-1]:
    for mod_bin in s['bin_labels']:
        pf_values[m][mod_bin][s['list_qtr'][1]] = [s['pf_init_value'], tax_rate, s['pf_init_value']]
#print(pf_values['diff_jaccard'])


# ## Calculate the value of the portfolio

# In[34]:


pf_scores = post_processing.calculate_portfolio_value(pf_scores, pf_values, lookup, stock_data, s)


# In[35]:


index_name = 'SPX'
display.diff_vs_benchmark(pf_values, index_name, index_data, s)


# In[36]:


for qtr in s['list_qtr'][1:]:
    print(qtr, pf_values['diff_jaccard']['Q5'][qtr][0])


# In[37]:


test_qtr_data = master_dict['diff_jaccard'][(2010, 2)]


# In[38]:


# [DEBUG] Show the Apple data for that time period
extracted_cik_scores = cik_scores[data_to_process[0][0]]
extracted_cik_scores


# In[39]:


#ticker = lookup[320193]
ticker = lookup[data_to_process[0][0]]
start_date = qtrs.qtr_to_day(s['time_range'][0], 'first', date_format='datetime')
stop_date = qtrs.qtr_to_day(s['time_range'][1], 'last', date_format='datetime')

#print(s['time_range'], start_date)
#print(s['time_range'], stop_date)
extracted_stock_data = {k: v for k, v in stock_data[ticker].items() if start_date <= k <= stop_date}
#print(extracted_data)


# # Display the data

# ## For a given ticker

# ### Metrics vs stock price

# In[40]:


display.diff_vs_stock(extracted_cik_scores, extracted_stock_data, ticker, s, method='diff')


# ### Sentiment vs stock price

# In[41]:


display.diff_vs_stock(extracted_cik_scores, extracted_stock_data, ticker, s, method='sentiment')


# In[ ]:



