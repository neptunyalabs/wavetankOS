"""
Pulls in test data from S3 and formats them in a set of dataframes per data record (testtype, throttle, measurement direction, ect)
"""

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

pst = pytz.timezone('US/Pacific')
utc = pytz.utc

def to_test_time(timestamp):
    dt = datetime.datetime.fromtimestamp(timestamp,tz=pytz.UTC)
    return dt.astimezone(pst)

def to_date(timestamp):
    return to_test_time(timestamp).date()

bucket = "neptunya-wave-data"
folder = "V1"

path = pathlib.Path(__file__)
fdir = path.parent
cache = diskcache.Cache(os.path.join(fdir,'data_cache'))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")

#TODO: deploy account for wave tank script
#AWS_ACCESS_KEY_ID = "AKIATRDFYHRDQGXS3LJ5"
#AWS_SECRET_ACCESS_KEY = "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"

#login
session = boto3.Session(profile_name='ottr-iot')
client = session.resource('s3')
bck = client.Bucket(bucket)

string_cols = ['title','test','date']
ign_cols = ['gap','sesh','t','sen1_x','sen2_x','timestamp','sen1_rot','sen2_rot','water_pla','air_pla']

low_pass_fraction = 0.05 #perecent of time series

#load all data chronologially
DT = 1.0 #"data gap"
records = {}
calibration = {}
for i,fil in enumerate(files := bck.objects.all()):

    if 'calibration' in fil.key:
        d = fil.get()
        log.info(f'loading {fil.key}')
        dj = json.loads(d['Body'].read().decode())

        calibration[fil.last_modified.timestamp()] = dj
        continue

    elif fil.key not in cache:
        log.info(f'downloading {fil.key}')
        d = fil.get()
        dj = json.loads(d['Body'].read().decode())
        cache[fil.key] = dj        
        for ts,row in dj['data'].items():
            records[ts] = row
    else:
        log.info(f'loading {fil.key}')
        dj = cache[fil.key]
        for ts,row in dj['data'].items():
            records[ts] = row

#Create Dataframe And Split By Date
tests = {}
data = pd.DataFrame.from_dict(list(records.values()))
data.sort_values('timestamp',inplace=True)
data['date'] = data['timestamp'].apply(to_date)

close('all')

#measure test duration for each test type
test_sessions = []

for dt,testdata in (test_days := data.groupby('date')):
    print(dt)
    ts_min = testdata.timestamp.min()
    ts_max = testdata.timestamp.max()
    cal_points =  dict(filter(lambda kv: kv[0] > ts_min and kv[0] < ts_max, calibration.items()))
    
    if any(testdata['water-pla']): 
        cal_ts = max([v for v in cal_points.keys()]) - ts_min

        #Setup test data
        testdata['t'] = testdata['timestamp'].apply(lambda ts: ts- ts_min )
        testdata= td = testdata.loc[testdata['t']>=cal_ts]
        testname = ' '.join([ v for v in set(td['test']) ])
        
        #setup plot
        fig,(ax1,ax3,ax2)= subplots(nrows=3,sharex=True)
        title = f'{testname} {dt}'.lower()
        fig.suptitle(title)
        
        ax1.scatter(testdata['t'],testdata['p1t'],alpha=0.5,s=1)
        ax3.scatter(testdata['t'],testdata['p2t'],alpha=0.5,s=1)        
        
        ax2.plot(testdata['t'],testdata['water-pla'],label='water/10')
        ax2.plot(testdata['t'],testdata['air-pla'],label='air/8')
        ax2.plot(testdata['t'],testdata['sen1-x'])
        ax2.plot(testdata['t'],testdata['sen2-x'],label='x mm')

        #add calibration points
        yset = ax2.get_ylim()
        for i,(cal_ts,calset) in enumerate(cal_points.items()):
            cal_ts = cal_ts-ts_min
            if i == 0:
                ax2.plot([cal_ts,cal_ts],yset,'k',label='cal')
            else:
                ax2.plot([cal_ts,cal_ts],'k',yset)
        
        ax2.legend()
        ax1.set_xlim([0,None])
        
        fig.savefig(os.path.join(fdir,title.replace(' ','_') + '.png'))

        #Break Down By Inputs
        for tset, tdd in testdata.groupby(by=list(['water-pla','air-pla','test','sen2-x'])):
            if 't' in tdd:
                ttime = diff(tdd['t'])

                #mark record breaks
                if any( ttime > DT ):
                    #print( f'big step,{tset}' )
                    tdd['gap'] = tdd['t'].diff() > DT
                    tdd['sesh'] = np.cumsum(tdd['gap'])
                else:
                    tdd['gap'] = False
                    tdd['sesh'] = 0
                
                #TODO: record sections of data by breaking between large gap(1s)
                ttime[ttime>DT] = min(ttime.mean(),1.0)
                for seshc, tddd in tdd.groupby(by='sesh'):
                    duration = sum(diff(tddd['t']))
                    if duration > 10.0:
                        
                        tss_min = tddd['timestamp'].min()
                        tss_max = tddd['timestamp'].max()

                        #Create Test Record
                        (wpla,apla,tst,xpos) = tset
                        D = {'wpla':wpla,'apla':apla,'xpos':xpos,'test':tst,'duration':duration,'ts_min':tss_min,'ts_max':tss_max}
                        test_sessions.append(D)

#POST PROCESS EACH SET AND CREATE SS POINT
al = 0.05
Kconst = 5E5
#TODO: make descision indpenenet of test data set length
for ts in test_sessions:
    wpla = ts['wpla']
    apla = ts['apla']
    xpos = ts['xpos']
    test = ts['test']
    tsmin,tsmax = ts['ts_min'],ts['ts_max']

    title = f'raw_test_{test}_{wpla}_{apla}_{xpos}_{int(tsmin)}.png'
    title = f'raw_test_{tsmin}_to_{tsmax}.png'
    log.info(f'creating {title}')
    ub=(data['timestamp'] >= tsmin).to_numpy()
    lb=(data['timestamp'] <= tsmax).to_numpy()
    tst_inx = np.logical_and(ub,lb)
    dat = data[  tst_inx ]
    
    pxlp = lambda: dat['timestamp']
    def pylp(y):
        dtt = dat[y].to_numpy()
        ylast = dtt[0]
        return [(ylast:=v*al + (1-al)*ylast) for v in dtt]
        
    diffx = pylp('p2t') - dat['p2t'].mean()
    errx = cumsum(diffx)
    
    fig,(a1,a2,a3,a4) = subplots(nrows=4,sharex=True)
    
    if (kerr:=((errx.max() - errx.min()) / Kconst)) > 1.0:
        dat_acc = dat[diffx>0]      
    else:
        dat_acc = dat

    #CALC VARIABLES:
    for tdc in dat_acc.columns:
        tdc = tdc.replace(' ','_').replace('-','_')
        if tdc not in string_cols and tdc not in ign_cols:
            #log.info(f'calculating {tdc}')
            row = dat_acc[tdc]
            ts[f'avg_{tdc}'] = row.mean()
            ts[f'std_{tdc}'] = row.std()
            ts[f'min_{tdc}'] = row.min()
            ts[f'max_{tdc}'] = row.max()
    
    px = lambda: (tsmin,tsmax)
    py = lambda y: (ts[y],ts[y])
    
    p = a1.scatter(dat.timestamp,dat.p1t,alpha=0.1,s=0.5,c='k')
    p = a1.scatter(dat_acc.timestamp,dat_acc.p1t,alpha=0.5,s=1.0,c='cyan')
    p = a1.plot(px(),py('avg_p1t'),'r--')
    p = a1.plot(pxlp(),pylp('p1t'),'m',alpha=0.5)

    p = a2.scatter(dat.timestamp,dat.p1s,alpha=0.1,s=0.5,c='k')
    p = a2.scatter(dat_acc.timestamp,dat_acc.p1s,alpha=0.5,s=1.0,c='cyan')
    p = a2.plot(px(),py('avg_p1s'),'r--')
    p = a2.plot(pxlp(),pylp('p1s'),'m',alpha=0.5)

    p = a3.scatter(dat.timestamp,dat.p2t,alpha=0.1,s=0.5,c='k')
    p = a3.scatter(dat_acc.timestamp,dat_acc.p2t,alpha=0.5,s=1.0,c='cyan')
    p = a3.plot(px(),py('avg_p2t'),'r--')
    p = a3.plot(pxlp(),pylp('p2t'),'m',alpha=0.5)

    p = a4.scatter(dat.timestamp,dat.p2s,alpha=0.1,s=0.5,c='k')
    p = a4.scatter(dat_acc.timestamp,dat_acc.p2s,alpha=0.5,s=1.0,c='cyan')
    p = a4.plot(px(),py('avg_p2s'),'r--')
    p = a4.plot(pxlp(),pylp('p2s'),'m',alpha=0.5)

    fig.savefig(os.path.join(fdir,'testpoints',title))
    close(fig)

#PERFORMANCE POINTS:
#Gather Duration Of All Data By Input Sets
rs = pd.DataFrame.from_dict(test_sessions)

pp1 = sns.pairplot(data=rs,vars=['wpla','apla','xpos','duration'],hue='test')
pp1.figure.savefig(os.path.join(fdir,'input_histplot.png'))
close(pp1.figure)


xvars = ['wpla','apla','xpos']
yvars = ['avg_p1t','avg_p2t','avg_p1s','avg_p2s']
pp2 = sns.pairplot(data=rs,x_vars=xvars,y_vars=yvars,hue='test')
pp2.figure.savefig(os.path.join(fdir,'data_histplot.png'))
close(pp2.figure)

#PRINT INFO
dataset = {}
for tst,rss in rs.groupby('test'):
    name = tst.upper()
    #print('\n'+('#'*80))
    print(name)
    #print(rss)
    dataset[name] = rss

# FILM TEST PLOT
rss['test'][rss.test=='DEMOCAL'] = 'FILMTEST'
fm = rss[rs.test=='FILMTEST']

aplas = [0,4,8]
wplas = [0,5,8,9,10]
fm_good = np.logical_and(np.isin(fm.wpla,wplas),np.isin(fm.apla,aplas))
fm = fm[fm_good]

for param in ['p1t','p1s','p2t','p2s']:
    g = sns.FacetGrid(fm,col='wpla')

    g.map_dataframe(sns.lineplot,x='xpos',y=f'avg_{param}',hue='apla')
    g.add_legend(title='Air Pla')

    title= f"Film Test: {param} Generation Vs Film Thickness For Water Flow"

    g.fig.suptitle(title,fontweight=5)
    g.fig.tight_layout()
    g.set_ylabels(label=f'{param} [Pa]')
    g.fig.savefig(f'film_test_plot_{param}.png')
    close(g.fig)

#TURBINE TEST
rss = rs
rss['is_turb'] = is_turb = rss['test'].map(lambda tst: 'TURBINE' in tst.upper())
rss['xpos'] = rss.xpos.to_numpy().astype(int)
rss['wpla'] = rss.wpla.to_numpy().astype(int)
rss['apla'] = rss.apla.to_numpy().astype(int)
turb_good = np.logical_and(is_turb,np.isin(rss.wpla,[0,5,8,9,10]))
rst = rss[np.logical_and(turb_good,rss.apla==0)]
#int measure weirdness
rst['xpos'][rst.xpos==2] = 3
rst['xpos'][rst.xpos==4] = 5
rst['xpos'][rst.xpos==7] = 8

sns.color_palette("rocket", as_cmap=True)

for param in ['p2t','p2s']:
    g = sns.FacetGrid(rst,col='test')
    g.map_dataframe(sns.lineplot,x='wpla',y=f'avg_{param}',hue='xpos')
    g.add_legend(title='x pos [mm]')

    title= f"Turbine Test: {param} Vs Film Thickness @ AIR = 0"

    g.fig.suptitle(title,fontweight=5)
    g.set_ylabels(label=f'{param} [Pa]')
    g.fig.tight_layout(rect=(0,0,0.9,0.95))
    g.fig.savefig(f'turb_test_plot_{param}.png')
    close(g.fig)