"""
Pulls in test data from S3 and formats them in a set of dataframes per data record (testtype, throttle, measurement direction, ect)
"""

from audioop import reverse
import enum
import logging
import boto3
import diskcache
import logging
import json
import pathlib
import os

from matplotlib.pylab import *
import pandas as pd
import pytz
import datetime
import seaborn as sns
import numpy as np

import glob

from waveware.config import *
from waveware.data import *

#login
#session = boto3.Session(profile_name=aws_profile)
#client = session.resource('s3')
#bck = client.Bucket(bucket)

min_span = 30


#low_pass_fraction = 0.05 #perecent of time series

nept_dir = pathlib.Path(os.path.abspath(__file__)).parent.parent.parent.parent
test_dir = os.environ.get('WAVEWARE_TESTDATA_DIR',os.path.join(nept_dir,'test_data'))
test_data = os.environ.get('WAVEWARE_TESTDATA_FLDR',os.path.join(test_dir,'v1'))
test_data = os.path.abspath(test_data)

results_dir = os.path.join(test_dir,'results')

def get_files(wildcard):
    files = glob.glob(os.path.join(test_data,wildcard),recursive=True)
    return [os.path.relpath(fil,test_data) for fil in files]

data_files = get_files('**/data_*.json')
input_files = get_files('**/set_input_*.json')
zero_files = get_files('**/zero*.json')
note_files = get_files('**/test_note*.json')


#Determine DataPoints To Get
data = {}
rec_times = {}
stop_times_ = []
for inpt_file in  input_files:
    with open(os.path.join(test_data,inpt_file),'r') as fp:
        inpt = json.load(fp)
    
    atime = datetime.datetime.fromisoformat(inpt['upload_time'])

    if 'mode' not in inpt['data'] or inpt['data']['mode'] != 'WAVE':
        #print(f"skipping  {inpt_file}| mode: {inpt['data']['mode']}")
        if inpt['data']['mode'].lower() in ['center','stop']:
            stop_times_.append(atime)
        continue

    rec_times[inpt_file] = atime
    data[inpt_file] = run_data = {'input':inpt,
                                  'start':atime,'end':None,'span':None,
                                  'notes':[],
                                  'records':{},
                                  'cal':{}
                                  }

#Determine Run Spans
stop_times = list(reversed(sorted(stop_times_)))
rec_times = {k:v for k,v in sorted(rec_times.items(),key=lambda kv: kv[-1]) } 
dtz =np.diff(list(rec_times.values()))

ends = []
starts = []
for i,(inpt,v) in enumerate(rec_times.items()):
    next_stop = None
    while stop_times and (next_stop:=stop_times.pop()) < data[inpt]['start']:
        pass

    dti = dtz[i] if i <= len(dtz)-1 else None
    
    if next_stop and next_stop < dti+data[inpt]['start']:
        dti = next_stop - data[inpt]['start']
        data[inpt]['end'] = next_stop
        data[inpt]['span'] = dti.total_seconds()        
    if dti:
        data[inpt]['end'] = data[inpt]['start'] + dti
        data[inpt]['span'] = dti.total_seconds()

    end = data[inpt]['end']
    if end:
        if (dtrng:=(end - data[inpt]['start']).total_seconds()) < min_span:
            data.pop(inpt)
            print(f'dropping short span: {dtrng}s | {inpt}')
        else:
            ends.append(end)
            starts.append(data[inpt]['start'])
    else:
        starts.append(data[inpt]['start'])

if len(ends) < len(starts):
    ends.append(datetime.datetime.utcnow())

ends = np.array(ends,dtype=np.datetime64)
starts = np.array(starts,dtype=np.datetime64)

test_dates = set([t.date() for t in rec_times.values()])

#Plot Record Times
# i = 0
# for inpt,dat in sorted(data.items(),key=lambda kv: kv[-1]['start']):
#     plot([dat['start'],dat['end']],[i,i])
#     i += 1

#Assign Data
notes= {}
#unassigned_data =  {}
records = list(data.keys())
for dat_fil in data_files:
    with open(os.path.join(test_data,dat_fil),'r') as fp:
        dat = json.load(fp)

    atime = datetime.datetime.fromisoformat(dat['upload_time'])

    mktime = atime.replace(tzinfo=None)
    iss = mktime >= starts
    ied = mktime-datetime.timedelta(seconds=min_span/2) <= ends

    match = np.logical_and(iss,ied)
    if np.any(match):
        cond = np.where(match==True)[0]
        for cnd in cond:
            key_rec = records[cnd]
            for ts,row in dat['data'].items():
                data[key_rec]['records'][row['timestamp']] = row
                row.update(data[key_rec]['input']['data'])

    #else:
    #    for ts,row in dat['data'].items():
    #        unassigned_data[row['timestamp' ]] = row

#sort data
for inpt_fil in data.keys():
    recs = dict(sorted(data[inpt_fil]['records'].items(), key=lambda kv: kv[0]))
    data[inpt_fil]['df']= df = pd.DataFrame(list(recs.values()))
    df['time'] = df['timestamp']-df['timestamp'].min() #time is relative!
    df['z2_abs'] = df['z2'] + df['z1']
    df['hs'] = df['wave-hs']
    df['wavelength'] = df['wave-hs']*df['wave-steep']
    df['wavespeed'] = 1.25 * (df['wavelength']**0.5)
    df['ts'] = df['wavelength'] / df['wavespeed']
    data[inpt_fil]['records'] = recs

#summary data
sum_dat = {}
for k,d in data.items():
    sum_dat[k]= di = d['input']['data'].copy()
    di['key'] = k
    di['at'] = d['input']['asOf']

df_sum = pd.DataFrame(list(sum_dat.values()))    
df_sum['hs'] = df_sum['wave-hs']
df_sum['wavelength'] = df_sum['wave-hs']*df_sum['wave-steep']
df_sum['wavespeed'] = 1.25 * (df_sum['wavelength']**0.5)
df_sum['ts'] = df_sum['wavelength'] / df_sum['wavespeed']   

df_sum.to_csv(os.path.join(results_dir,f'summary.csv'))

#Summary Plot
fig,ax = subplots(figsize=(10,10))
for title,dfs in df_sum.groupby('title'):
    if not any([t in  title.lower() for t in ['bouy','spring']]):
        continue
    #for hs,dfh in dfs.groupby('hs'):
    ax.scatter(dfs.ts,dfs.hs,label=title,alpha=0.5,s=10)
ax.legend()
ax.grid()
ax.set_xlabel('Ts')
ax.set_ylabel('Hs')
fig.savefig(os.path.join(results_dir,f'summary_plot.png'))

fig,ax = subplots(figsize=(10,10))
for title,dfs in df_sum.groupby('title'):
    if not any([t in  title.lower() for t in ['bouy','spring']]):
        continue
    #for hs,dfh in dfs.groupby('hs'):
    ax.scatter(dfs['wave-steep'],dfs.hs,label=title,alpha=0.5,s=10)
ax.legend()
ax.grid()
ax.set_xlabel('Steep')
ax.set_ylabel('Hs')
fig.savefig(os.path.join(results_dir,f'steepsum_plot.png'))


#Map Calibration Files While Running
records = list(data.keys())
for zro_fil in zero_files:
    with open(os.path.join(test_data,zro_fil),'r') as fp:
        dat = json.load(fp)

    atime = datetime.datetime.fromisoformat(dat['upload_time'])

    mktime = atime.replace(tzinfo=None)
    iss = mktime >= starts
    ied = mktime <= ends

    match = np.logical_and(iss,ied)
    if np.any(match):
        cond = np.where(match==True)[0]
        for cnd in cond:
            if cnd not in records:
                continue
            key_rec = records[cnd]
            if key_rec not in data:
                continue
            data[key_rec]['cal'].append(dat)
        
for note_fil in note_files:
    with open(os.path.join(test_data,note_fil),'r') as fp:
        dat = json.load(fp)
    
    notes[note_fil] = dat['test_log']

    atime = datetime.datetime.fromisoformat(dat['at'])

    mktime = atime.replace(tzinfo=None)
    iss = mktime >= starts
    ied = mktime <= ends

    match = np.logical_and(iss,ied)
    if np.any(match):
        cond = np.where(match==True)[0]
        for cnd in cond:
            if cnd not in records:
                continue
            key_rec = records[cnd]
            if key_rec not in data:
                continue
            data[key_rec]['notes'].append(note_fil)

#plot 1 time vs encoder pos & wave heights
y1 = ['z1','z2_abs']
for i,(inpt,dat) in enumerate(data.items()):
    fig,ax = subplots(figsize=(12,6))
    df = dat['df']
    L = df.iloc[0]
    hs = L['hs']
    ts = L['ts']
    case = L['title']

    title = f'Run {i}: {case} | Hs: {hs:5.4f} Ts: {ts:5.4f}'
    print(f'plotting {title}')

    case_dir = os.path.join(results_dir,case.replace('-','_'))
    os.makedirs(case_dir,exist_ok=True,mode=754)
    df.to_csv(os.path.join(case_dir,f'run_{i}.csv'))
    for y in y1:
        ax.plot(df.time,df[y],label=y)
    ax.grid()
    ax.legend()
    ax.set_title(title)
    fig.savefig(os.path.join(case_dir,f'run_{i}.png'))







































#ARCHIVE
# 
# #measure test duration for each test type
# test_sessions = []
# 
# for dt,testdata in (test_days := data.groupby('date')):
#     log.info(dt)
#     ts_min = testdata.timestamp.min()
#     ts_max = testdata.timestamp.max()
#     cal_points =  dict(filter(lambda kv: kv[0] > ts_min and kv[0] < ts_max, calibration.items()))
#     
#     if any(testdata['water-pla']): 
#         cal_ts = max([v for v in cal_points.keys()]) - ts_min
# 
#         #Setup test data
#         testdata['t'] = testdata['timestamp'].apply(lambda ts: ts- ts_min )
#         testdata= td = testdata.loc[testdata['t']>=cal_ts]
#         testname = ' '.join([ v for v in set(td['test']) ])
#         
#         #setup plot
#         fig,(ax1,ax3,ax2)= subplots(nrows=3,sharex=True)
#         title = f'{testname} {dt}'.lower()
#         fig.suptitle(title)
#         
#         ax1.scatter(testdata['t'],testdata['p1t'],alpha=0.5,s=1)
#         ax3.scatter(testdata['t'],testdata['p2t'],alpha=0.5,s=1)        
#         
#         ax2.plot(testdata['t'],testdata['water-pla'],label='water/10')
#         ax2.plot(testdata['t'],testdata['air-pla'],label='air/8')
#         ax2.plot(testdata['t'],testdata['sen1-x'])
#         ax2.plot(testdata['t'],testdata['sen2-x'],label='x mm')
# 
#         #add calibration points
#         yset = ax2.get_ylim()
#         for i,(cal_ts,calset) in enumerate(cal_points.items()):
#             cal_ts = cal_ts-ts_min
#             if i == 0:
#                 ax2.plot([cal_ts,cal_ts],yset,'k',label='cal')
#             else:
#                 ax2.plot([cal_ts,cal_ts],'k',yset)
#         
#         ax2.legend()
#         ax1.set_xlim([0,None])
#         
#         fig.savefig(os.path.join(fdir,title.replace(' ','_') + '.png'))
# 
#         #Break Down By Inputs
#         for tset, tdd in testdata.groupby(by=list(['water-pla','air-pla','test','sen2-x'])):
#             if 't' in tdd:
#                 ttime = diff(tdd['t'])
# 
#                 #mark record breaks
#                 if any( ttime > DT ):
#                     #log.info( f'big step,{tset}' )
#                     tdd['gap'] = tdd['t'].diff() > DT
#                     tdd['sesh'] = np.cumsum(tdd['gap'])
#                 else:
#                     tdd['gap'] = False
#                     tdd['sesh'] = 0
#                 
#                 #TODO: record sections of data by breaking between large gap(1s)
#                 ttime[ttime>DT] = min(ttime.mean(),1.0)
#                 for seshc, tddd in tdd.groupby(by='sesh'):
#                     duration = sum(diff(tddd['t']))
#                     if duration > 10.0:
#                         
#                         tss_min = tddd['timestamp'].min()
#                         tss_max = tddd['timestamp'].max()
# 
#                         #Create Test Record
#                         (wpla,apla,tst,xpos) = tset
#                         D = {'wpla':wpla,'apla':apla,'xpos':xpos,'test':tst,'duration':duration,'ts_min':tss_min,'ts_max':tss_max}
#                         test_sessions.append(D)
# 
# #POST PROCESS EACH SET AND CREATE SS POINT
# al = 0.05
# Kconst = 5E5
# #TODO: make descision indpenenet of test data set length
# for ts in test_sessions:
#     wpla = ts['wpla']
#     apla = ts['apla']
#     xpos = ts['xpos']
#     test = ts['test']
#     tsmin,tsmax = ts['ts_min'],ts['ts_max']
# 
#     title = f'raw_test_{test}_{wpla}_{apla}_{xpos}_{int(tsmin)}.png'
#     title = f'raw_test_{tsmin}_to_{tsmax}.png'
#     log.info(f'creating {title}')
#     ub=(data['timestamp'] >= tsmin).to_numpy()
#     lb=(data['timestamp'] <= tsmax).to_numpy()
#     tst_inx = np.logical_and(ub,lb)
#     dat = data[  tst_inx ]
#     
#     pxlp = lambda: dat['timestamp']
#     def pylp(y):
#         dtt = dat[y].to_numpy()
#         ylast = dtt[0]
#         return [(ylast:=v*al + (1-al)*ylast) for v in dtt]
#         
#     diffx = pylp('p2t') - dat['p2t'].mean()
#     errx = cumsum(diffx)
#     
#     fig,(a1,a2,a3,a4) = subplots(nrows=4,sharex=True)
#     
#     if (kerr:=((errx.max() - errx.min()) / Kconst)) > 1.0:
#         dat_acc = dat[diffx>0]      
#     else:
#         dat_acc = dat
# 
#     #CALC VARIABLES:
#     for tdc in dat_acc.columns:
#         tdc = tdc.replace(' ','_').replace('-','_')
#         if tdc not in string_cols and tdc not in ign_cols:
#             #log.info(f'calculating {tdc}')
#             row = dat_acc[tdc]
#             ts[f'avg_{tdc}'] = row.mean()
#             ts[f'std_{tdc}'] = row.std()
#             ts[f'min_{tdc}'] = row.min()
#             ts[f'max_{tdc}'] = row.max()
#     
#     px = lambda: (tsmin,tsmax)
#     py = lambda y: (ts[y],ts[y])
#     
#     p = a1.scatter(dat.timestamp,dat.p1t,alpha=0.1,s=0.5,c='k')
#     p = a1.scatter(dat_acc.timestamp,dat_acc.p1t,alpha=0.5,s=1.0,c='cyan')
#     p = a1.plot(px(),py('avg_p1t'),'r--')
#     p = a1.plot(pxlp(),pylp('p1t'),'m',alpha=0.5)
# 
#     p = a2.scatter(dat.timestamp,dat.p1s,alpha=0.1,s=0.5,c='k')
#     p = a2.scatter(dat_acc.timestamp,dat_acc.p1s,alpha=0.5,s=1.0,c='cyan')
#     p = a2.plot(px(),py('avg_p1s'),'r--')
#     p = a2.plot(pxlp(),pylp('p1s'),'m',alpha=0.5)
# 
#     p = a3.scatter(dat.timestamp,dat.p2t,alpha=0.1,s=0.5,c='k')
#     p = a3.scatter(dat_acc.timestamp,dat_acc.p2t,alpha=0.5,s=1.0,c='cyan')
#     p = a3.plot(px(),py('avg_p2t'),'r--')
#     p = a3.plot(pxlp(),pylp('p2t'),'m',alpha=0.5)
# 
#     p = a4.scatter(dat.timestamp,dat.p2s,alpha=0.1,s=0.5,c='k')
#     p = a4.scatter(dat_acc.timestamp,dat_acc.p2s,alpha=0.5,s=1.0,c='cyan')
#     p = a4.plot(px(),py('avg_p2s'),'r--')
#     p = a4.plot(pxlp(),pylp('p2s'),'m',alpha=0.5)
# 
#     fig.savefig(os.path.join(fdir,'testpoints',title))
#     close(fig)
# 
# #PERFORMANCE POINTS:
# #Gather Duration Of All Data By Input Sets
# rs = pd.DataFrame.from_dict(test_sessions)
# 
# pp1 = sns.pairplot(data=rs,vars=['wpla','apla','xpos','duration'],hue='test')
# pp1.figure.savefig(os.path.join(fdir,'input_histplot.png'))
# close(pp1.figure)
# 
# 
# xvars = ['wpla','apla','xpos']
# yvars = ['avg_p1t','avg_p2t','avg_p1s','avg_p2s']
# pp2 = sns.pairplot(data=rs,x_vars=xvars,y_vars=yvars,hue='test')
# pp2.figure.savefig(os.path.join(fdir,'data_histplot.png'))
# close(pp2.figure)
# 
# #PRINT INFO
# dataset = {}
# for tst,rss in rs.groupby('test'):
#     name = tst.upper()
#     #log.info('\n'+('#'*80))
#     log.info(name)
#     #log.info(rss)
#     dataset[name] = rss
# 
# # FILM TEST PLOT
# rss['test'][rss.test=='DEMOCAL'] = 'FILMTEST'
# fm = rss[rs.test=='FILMTEST']
# 
# aplas = [0,4,8]
# wplas = [0,5,8,9,10]
# fm_good = np.logical_and(np.isin(fm.wpla,wplas),np.isin(fm.apla,aplas))
# fm = fm[fm_good]
# 
# for param in ['p1t','p1s','p2t','p2s']:
#     g = sns.FacetGrid(fm,col='wpla')
# 
#     g.map_dataframe(sns.lineplot,x='xpos',y=f'avg_{param}',hue='apla')
#     g.add_legend(title='Air Pla')
# 
#     title= f"Film Test: {param} Generation Vs Film Thickness For Water Flow"
# 
#     g.fig.suptitle(title,fontweight=5)
#     g.fig.tight_layout()
#     g.set_ylabels(label=f'{param} [Pa]')
#     g.fig.savefig(f'film_test_plot_{param}.png')
#     close(g.fig)
# 
# #TURBINE TEST
# rss = rs
# rss['is_turb'] = is_turb = rss['test'].map(lambda tst: 'TURBINE' in tst.upper())
# rss['xpos'] = rss.xpos.to_numpy().astype(int)
# rss['wpla'] = rss.wpla.to_numpy().astype(int)
# rss['apla'] = rss.apla.to_numpy().astype(int)
# turb_good = np.logical_and(is_turb,np.isin(rss.wpla,[0,5,8,9,10]))
# rst = rss[np.logical_and(turb_good,rss.apla==0)]
# #int measure weirdness
# rst['xpos'][rst.xpos==2] = 3
# rst['xpos'][rst.xpos==4] = 5
# rst['xpos'][rst.xpos==7] = 8
# 
# sns.color_palette("rocket", as_cmap=True)
# 
# for param in ['p2t','p2s']:
#     g = sns.FacetGrid(rst,col='test')
#     g.map_dataframe(sns.lineplot,x='wpla',y=f'avg_{param}',hue='xpos')
#     g.add_legend(title='x pos [mm]')
# 
#     title= f"Turbine Test: {param} Vs Film Thickness @ AIR = 0"
# 
#     g.fig.suptitle(title,fontweight=5)
#     g.set_ylabels(label=f'{param} [Pa]')
#     g.fig.tight_layout(rect=(0,0,0.9,0.95))
#     g.fig.savefig(f'turb_test_plot_{param}.png')
#     close(g.fig)
