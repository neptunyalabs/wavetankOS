"""
Pulls in test data from S3 and formats them in a set of dataframes per data record (testtype, throttle, measurement direction, ect)
"""

from audioop import reverse
import enum
import logging

from requests import head
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
from numpy.lib import stride_tricks  as stld

import pysindy as ps
import scipy.optimize as sciopt
from scipy import signal

import glob
import subprocess


from waveware.config import *
from waveware.data import *

logging.basicConfig(level=20)
log = logging.getLogger('post-processing')

min_span = 20


#low_pass_fraction = 0.05 #perecent of time series

nept_dir = pathlib.Path(os.path.abspath(__file__)).parent.parent.parent.parent
test_dir = os.environ.get('WAVEWARE_TESTDATA_DIR',os.path.join(nept_dir,'test_data'))
test_data = os.environ.get('WAVEWARE_TESTDATA_FLDR',os.path.join(test_dir,folder.lower()))
test_data = os.path.abspath(test_data)

results_dir = os.path.join(test_dir,'results')
os.makedirs(results_dir,mode=754,exist_ok=True)

def get_files(wildcard):
    files = glob.glob(os.path.join(test_data,wildcard),recursive=True)
    return [os.path.relpath(fil,test_data) for fil in files]


def sync_from_s3():
    pth = f's3://{bucket}/{folder}'
    log.info(f'running S3 Sync from: {pth} to: {test_data}')

    #login
    result = subprocess.run(f'aws s3 sync "{pth}" "{test_data}"',shell=True, text=True,env=os.environ)
    log.info(f'sync result: {result}')

data_files = get_files('**/data_*.json')
input_files = get_files('**/set_input_*.json')
zero_files = get_files('**/zero*.json')
note_files = get_files('**/test_note*.json')
maybe_note_files = get_files('**/session_results*.json') #notes labled wrong :(

def load_data():
    #Determine DataPoints To Get

    log.info(f'loading data...')

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

    #order datas
    data = dict({k:v for k,v in sorted(data.items(),key=lambda kv: kv[1]['start'])})


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
                #TODO: fix record ordering issue?
                key_rec = records[cnd]
                for ts,row in dat['data'].items():
                    row.update(**data[key_rec]['input']['data'])
                    data[key_rec]['records'][row['timestamp']] = row.copy()

        #else:
        #    for ts,row in dat['data'].items():
        #        unassigned_data[row['timestamp' ]] = row

    #sort data
    rmv = []
    for inpt_fil in data.keys():
        recs = dict(sorted(data[inpt_fil]['records'].items(), key=lambda kv: kv[0]))
        if recs:
            data[inpt_fil]['df']= df = pd.DataFrame(list(recs.values()))
            L = df.iloc[0]
            case = L['title']
            #print(f'case: {case} from {inpt_fil}')   
            df['time'] = df['timestamp']-df['timestamp'].min() #time is relative!
            df['z2_abs'] = df['z2'] + df['z1']
            df['hs'] = df['wave-hs']
            df['wavelength'] = df['wave-hs']*df['wave-steep']
            df['wavespeed'] = 1.25 * (df['wavelength']**0.5)
            df['ts'] = df['wavelength'] / df['wavespeed']
            df['az_acl'] = df['az'] - df['az'].mean()
            data[inpt_fil]['records'] = recs
        else:
            print(f'no data: {inpt_fil}')
            rmv.append(inpt_fil)

    for rm in rmv:
        data.pop(rm)

    #Map Calibration Files While Running
    cals = {}
    records = list(data.keys())
    for zro_fil in zero_files:
        with open(os.path.join(test_data,zro_fil),'r') as fp:
            dat = json.load(fp)

        atime = datetime.datetime.fromisoformat(dat['upload_time'])

        mktime = atime.replace(tzinfo=None)
        iss = mktime >= starts
        ied = mktime <= ends
        cals[mktime] = mktime
        
        def insert(k,x):
            if key_rec not in data:
                return
            cal = data[key_rec]['cal']        
            if isinstance(cal,list):
                cal.append(x)
            else:
                cal.update({f'{mktime}':x})

        match = np.logical_and(iss,ied)
        if np.any(match):
            cond = np.where(match==True)[0]
            for cnd in cond:
                key_rec = records[min(cnd,len(records)-1)]
                insert(key_rec,dat)
        else:#cal only goes to 
            nptm =np.datetime64(mktime)
            dstmk = (nptm - starts).astype(int)
            denmk = (ends -nptm).astype(int)

            stval = np.min( dstmk[dstmk>=0] )
            stinx = int(np.where(dstmk==stval)[0])
            key_rec = records[stinx]
            insert(key_rec,dat)    
            
            
    for note_fil in (note_files+maybe_note_files):
        with open(os.path.join(test_data,note_fil),'r') as fp:
            dat = json.load(fp)

        if 'test_log' not in dat:
            log.info(f'skipping not log: {test_data}/{note_fil}| {dat}')
            continue

        notes[note_fil] = note = dat['test_log']

        atime = datetime.datetime.fromisoformat(dat['at'])

        mktime = atime.replace(tzinfo=None)
        iss = mktime >= starts
        ied = mktime <= ends

        match = np.logical_and(iss,ied)
        if np.any(match):
            cond = np.where(match==True)[0]
            for cnd in cond:
                key_rec = records[min(cnd,len(records)-1)]
                if key_rec not in data:
                    continue
                data[key_rec]['notes'].append(note)

        else: #add notes to both before and after runs (config/issues)
            nptm =np.datetime64(mktime)
            dstmk = (nptm - starts).astype(int)
            denmk = (ends -nptm).astype(int)

            stval = np.min( dstmk[dstmk>=0] )
            stinx = int(np.where(dstmk==stval)[0])
            key_rec = records[stinx]
            if key_rec not in data:
                continue
            data[key_rec]['notes'].append(note)     

            enval = np.max( denmk[denmk<=0] )
            eninx = int(np.where(denmk==enval)[0])
            key_rec = records[eninx]
            if key_rec not in data:
                continue
            data[key_rec]['notes'].append(note)

    #with open(os.path.join(results_dir,f'data.json'),'w') as fp:
    #    fp.write(json.dumps(data))

    out = {'data':data,
           'starts':starts,
           'end':ends,
           'notes': notes,
           'records':records,
           'cal':cals}

    return out


header_columns = ['title','at','notes','hs','ts']
def create_summary(data):

    log.info(f'creating summary...')

    #summary data
    sum_dat = {}
    for i,(k,d) in enumerate(data.items()):
        sum_dat[k]= di = d['input']['data'].copy()
        di['key'] = k
        di['at'] = d['input']['asOf']
        di['notes'] = '\n'.join(d['notes'])
        di['cal'] = d['cal']

    df_sum = pd.DataFrame(list(sum_dat.values()))
    df_sum['hs'] = df_sum['wave-hs']
    df_sum['wavelength'] = df_sum['wave-hs']*df_sum['wave-steep']
    df_sum['wavespeed'] = 1.25 * (df_sum['wavelength']**0.5)
    df_sum['ts'] = df_sum['wavelength'] / df_sum['wavespeed']

    cols = [c for c in df_sum.columns.tolist() if c not in header_columns]
    cols = header_columns + cols
    df_sum = df_sum[cols]
    df_sum.to_csv(os.path.join(results_dir,f'summary.csv'),index=False)

    return df_sum

def load_summary():
    pth = os.path.join(results_dir,f'summary.csv')
    log.info(f'loading summary from: {pth}')
    df_sum = pd.read_csv(pth)
    return df_sum

def plot_summary(df_sum):
    #Summary Plot

    log.info(f'plotting summary to: {results_dir}')

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
    close('all')

    for title,dfs in df_sum.groupby('title'):
        if not any([t in  title.lower() for t in ['bouy','spring']]):
            continue

        fig,ax = subplots(figsize=(10,10))
        ax.scatter(dfs['wave-steep'],dfs.hs,label=title,alpha=0.5,s=10)
        ax.legend()
        ax.grid()
        ax.set_xlabel('Steep')
        ax.set_ylabel('Hs')
        ax.set_title(title)
        fig.savefig(os.path.join(results_dir,f'steepsum_{title}_plot.png'))
        close('all')  



def plot_data(data):
    #plot 1 time vs encoder pos & wave heights

    log.info(f'plotting data to: {results_dir}')

    y1 = ['z1','z2']
    y2 = ['az_acl','ax','ay']
    y3 = ['gz','gx','gy']
    ys = [y1,y2,y3]
    for i,(inpt,dat) in enumerate(data.items()):
        
        df = dat['df']
        L = df.iloc[0]
        hs = L['hs']
        ts = L['ts']
        case = L['title']

        title = f'Run {i}: {case} | Hs: {hs:5.4f} Ts: {ts:5.4f}'
        print(f'plotting {title} from {inpt} inpt: {dat["input"]["data"]["title"]}')

        case_dir = os.path.join(results_dir,case.replace('-','_').strip())
        os.makedirs(case_dir,exist_ok=True,mode=754)
        df.to_csv(os.path.join(case_dir,f'run_{i}.csv'))
        fig,axs = subplots(nrows=len(ys),figsize=(24,6),sharex=True)
        for pj,yss in enumerate(ys):
            for y in yss:
                #dont plot constants
                if df[y].max() == df[y].mean():
                    continue
                yz = df[y]
                if y in y1:
                    yz = yz.copy() - yz.mean()
                axs[pj].plot(df.time,yz,label=y)
            axs[pj].grid()
            axs[pj].legend()
        fig.suptitle(title)
        fig.savefig(os.path.join(case_dir,f'run_{i}.png'))
        close('all')


def get_run_data(df_sum,run_id):
    title = df_sum['title'].iloc[run_id]
    case = title.replace('-','_').strip()
    path = os.path.join(results_dir,case,f'run_{run_id}.csv')
    print(f'getting: {title} | run: {run_id}')
    notes = df_sum['notes'].iloc[run_id]
    print(f'notes: {notes}')
    return pd.read_csv(path)


def diff_values(zz):
    bcoef, acoef = signal.butter(3, 0.01)

    v = np.concatenate(([0],np.diff(zz)))
    a = np.concatenate(([0],np.diff(v)))
    
    ac_max = np.abs(a).max()
    vc_max = np.abs(v).max()
    
    mot =  ((v/vc_max)**2 + (a/ac_max)**2)**0.5
    mot_sig = signal.filtfilt(bcoef,acoef, mot)
    min_val = mot_sig.max()/len(zz)
    mot_sig[mot_sig<= min_val] = min_val
    mot_weights = 1/mot_sig
    
    return v,a,mot_weights

def process_runs(df_sum,**kwargs):

    for rec in df_sum.iloc:
        try:
            process_run(df_sum,rec.name,**kwargs)
        except Exception as e:
            print(f'error: {e}')

    df_sum.to_csv(os.path.join(results_dir,f'summary.csv'),index=False)

def process_run(df_sum,run_id,u_key='z_wave',plot=False):
    """provided the summary dataframe and the index id, gather dataframe and analyze"""

    rec = df_sum.iloc[run_id]
    dfr = get_run_data(df_sum,run_id)

    time = tm = dfr['time']

    wave_omg = 2*3.14159/rec['ts']

    #estimate offset for wave impact
    tm_x = df_sum['wavespeed'].iloc[run_id]*1.5 #5ft

    z1_vel,z1_acc,mot_weights = diff_values(dfr['z1'])
    z1_pos = np.average(dfr['z1'],weights=mot_weights)
    z1 = dfr['z1'] - z1_pos
    
    no_z1 = False
    if np.any(z1.isna()):
        no_z1 = True
        z1 = np.zeros(z1.shape)
        a1 = np.zeros(z1.shape)
    else:
        z1 = z1.to_numpy()
        a1 = z1_acc

    if no_z1:    
        z2_vel,z2_acc,z2_wght= diff_values(dfr['z2'])
        z2_pos = np.average(dfr['z2'],weights=z2_wght)
        z2 = dfr['z2'] - z2_pos
    else:
        z2_vel,z2_acc,z2_wght= diff_values(dfr['z2_abs'])
        z2_pos = np.average(dfr['z2_abs'],weights=z2_wght)
        z2 = dfr['z2_abs'] - z2_pos        

    a2 = dfr['az'] - dfr['az'].mean()
    
    key = 'z_wave'
    hs = rec['hs']
    scale = 1000 * hs/(dfr[key].max() - dfr[key].min())

    z_act = scale*dfr[u_key]
    v_wc,a_wc,wave_wght = diff_values(z_act)
    za_pos = np.average(z_act,weights=wave_wght)
    z_act = z_act - za_pos

    def f(toff,tm,zza,zz1):
        #t1 = tm.copy()
        zzprime = np.interp(tm,tm+toff,zza)
        return (np.sum((zzprime-zz1)**2))**0.5

    time_fit = tm[:int(len(tm)/2)]
    ww = (wave_wght/wave_wght.max())[:int(len(tm)/2)]
    w2 = (z2_wght/z2_wght.max())[:int(len(tm)/2)]

    bnd = [tm_x*0.5,tm_x*1.5]
    args = (time_fit,ww,w2)
    ans = sciopt.minimize_scalar(f,bounds=bnd,args=args)
    toff = ans.x
    xf = np.interp(tm,tm+toff,z_act)
    x1 = z1
    x2 = z2.to_numpy()
    v1 = z1_vel
    v2 = z2_vel
    a1 = a1

    #Max Filter Analysis
    dt = np.median(np.diff(time))
    N_osll = int(rec['ts']/dt)
    z1_hmax = stld.sliding_window_view(z1,N_osll).max(axis=1)
    z1_hmin = stld.sliding_window_view(z1,N_osll).min(axis=1)
    z2_hmax = stld.sliding_window_view(z2,N_osll).max(axis=1)
    z2_hmin = stld.sliding_window_view(z2,N_osll).min(axis=1)
    zf_hmax = stld.sliding_window_view(xf,N_osll).max(axis=1)
    zf_hmin = stld.sliding_window_view(xf,N_osll).min(axis=1)      
    tm_roll = stld.sliding_window_view(tm,N_osll).max(axis=1)

    hs_zf = zf_hmax - zf_hmin
    hs_z1 = z1_hmax - z1_hmin
    hs_z2 = z2_hmax - z2_hmin

    hinx = hs_zf >= 1
    hfact2 = np.median(hs_z2[hinx]/hs_zf[hinx])
    hfact1 = np.median(hs_z1[hinx]/hs_zf[hinx])

    #zero cross estimate
    zc_time = z1[:-1]*z1[1:]
    zc_times = (time[1:][zc_time <= 0])
    dt_zc = np.diff(zc_times).mean()
    ts_est = dt_zc*2

    analysis_kw = dict(
    N_osll = N_osll,
    z1_hmax = z1_hmax,
    z1_hmin = z1_hmin,
    z2_hmax = z2_hmax,
    z2_hmin = z2_hmin,
    zf_hmax = zf_hmax,
    zf_hmin = zf_hmin,
    hs_zf = hs_zf,
    hs_z1 = hs_z1,
    hs_z2 = hs_z2,
    ts_est =ts_est,

    hfact2 = hfact2,
    hfact1 = hfact1,
    toff=toff,
    dt=dt,
    omg=wave_omg,
    dof_3d=no_z1
    )

    for k,v in analysis_kw.items():
        if isinstance(v,(float,int,bool)):
            if k not in df_sum:
                df_sum[k] = None
            df_sum.loc[run_id,k] = v


    fig,ax = None,None
    if plot:
        fig,(ax,ax2) = subplots(nrows=2,figsize=(20,10),sharex=True)
        ax.scatter(tm,z1,c='m',label='z1',alpha=0.7,s=1)
        ax.plot(tm,z1,'m',alpha=0.5)
        ax.plot(tm_roll,z1_hmax,'m--',alpha=0.25)
        ax.plot(tm_roll,z1_hmin,'m--',alpha=0.25)
        ax.scatter(tm,z2,c='c',label='z2',alpha=0.7,s=1)
        ax.plot(tm,z2,'c',alpha=0.5)
        ax.plot(tm_roll,z2_hmax,'c--',alpha=0.25)
        ax.plot(tm_roll,z2_hmin,'c--',alpha=0.25)        
        ax.plot(tm,xf,'k',label='za',alpha=0.1)
        ax.plot(tm_roll,zf_hmax,'b--',alpha=0.25)
        ax.plot(tm_roll,zf_hmin,'b--',alpha=0.25)       
        ax.grid()
        ax.legend()
        ax.set_title(f'Run {run_id}| {rec["title"]} |Hs: {rec["hs"]:5.4f} Ts: {rec["ts"]:5.4f}')

        ax2.plot(tm,xf,'k',label='za',alpha=0.1)
        ax2.plot(tm,a1,'m',label='a1',alpha=0.5)
        ax2.plot(tm,a2,'c',label='a2',alpha=0.5)
        ax2.plot(tm,v1,'g',label='v1',alpha=0.5)
        ax2.plot(tm,v2,'b',label='v2',alpha=0.5)
        ax2.grid()
        ax2.legend()
        
        case = rec['title']
        case_dir = os.path.join(results_dir,case.replace('-','_').strip())
        os.makedirs(case_dir,exist_ok=True,mode=754)
        fig.savefig(os.path.join(case_dir,f'analy_{run_id}.png'))

        close()     
    
    time = time.to_numpy()

    out = dict(z1=x1,z2=x2,v1=v1,v2=v2,xf=xf,a1=a1,a2=a2,df=dfr,rec=rec,time=time,z_act=z_act,toff=toff,fig=fig,ax=ax,dof_3d=no_z1,dt=dt,omg=wave_omg,ts=rec['ts'],hs=rec['hs'],analysisKw=analysis_kw)

    return out



def main():
    """runs the cli for post-processing"""
    import argparse

    parser = argparse.ArgumentParser('WaveTank OS Post-Processing')

    kwarg = {'action':'store_true'}
    parser.add_argument('-SY','--sync',help='downloads from S3',**kwarg)
    parser.add_argument('-LD','--load',help='load data to `data`',**kwarg)
    parser.add_argument('-SM','--summary', help='activates --load if called',**kwarg)
    parser.add_argument('-PR','--process', help='run processing and add data to summary',**kwarg)    
    parser.add_argument('-LS','--load-summary', help='activates --load if called',**kwarg)
    parser.add_argument('-PS','--pl-sum', help='activates --load and -sum if called',**kwarg)
    parser.add_argument('-PD','--plot-data', help='activates --load if called',**kwarg)
    parser.add_argument('-RA','--run-all', help='runs everything',**kwarg)

    args = parser.parse_args()

    data = None
    df_sum = None

    if args.sync or args.run_all:
        sync_from_s3()

    if args.load or args.summary or args.pl_sum or args.plot_data or args.run_all:
        data = load_data()

    if args.summary or args.run_all:
        df_sum = create_summary(data['data'])

    elif args.load_summary or args.pl_sum:
        df_sum = load_summary()

    if args.process or args.run_all:
        do_plot = args.plot_data or args.run_all
        process_runs(df_sum,plot=do_plot)

    if args.pl_sum or args.run_all:
        plot_summary(df_sum)

    if data and args.plot_data or args.run_all:
        plot_data(data['data'])

    return data,df_sum


if __name__ == '__main__':

    out,df_sum = main()    








