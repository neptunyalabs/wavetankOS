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
import traceback
import typing
import fnmatch
import time

from sympy import EX

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
    run_id = 0
    for inpt_fil in data.keys():
        recs = dict(sorted(data[inpt_fil]['records'].items(), key=lambda kv: kv[0]))
        if recs:
            run_id += 1
            data[inpt_fil]['run_id'] = run_id
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

            case_dir = os.path.join(results_dir,case.replace('-','_').strip())
            os.makedirs(case_dir,exist_ok=True,mode=754)
            time.sleep(1)
            df.to_csv(os.path.join(case_dir,f'run_{run_id}.csv')) 

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
        di['run_id'] = d['run_id']

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


valid_fitler_keys = set(['parm','fnmatch','regex','callable','no_match'])

def categorize_summary(df_sum,filt:typing.Union[dict],prevent_override=False):
    """
    applies new columns in the filter dictionary based on the contents of a column defined by `parm`, with matching filter rules based on `fnmatch`, `regex` or `callable` rules. 
    
    Each filter set will write the key of the matching sub-dictionary if it matches anything. For string matches the underlying data will be put in lowercase first. If no match is found None will be inserted, if `no_match` key exists in the filter rule that value will be used (only applies for fnmatch and regex)
    
    example filter:
    .. highlight:: python
    .. code-block:: python

        exfilter = dict(
        test_type = {'parm':'title', 'fnmatch':{'bouy 1': ['bouy 1*','test-*'],
                                                'bouy 2': ['bouy 2*','bouy2*'],
                                                '3d': ['3d motion*','3dmotion*']},
        power_ext = {'parm':'title', 'regex': {'pto': ['.*-spring.*','.*pto.*']},
                                            'no_match': 'no_pto'},
        custom = {'parm':'title', 'callable': lambda x: x.lower().strip()})
    """
    for new_parm,filter_rule in filt.items():
        assert set(filter_rule.keys()).issubset(valid_fitler_keys), f"invalid fitler rule for {new_parm}, should only contain keys in {valid_fitler_keys}"
        
        if prevent_override:
            assert new_parm not in df_sum.columns, f'not allowed to override existing columns'
        
        #Apply Matching Rules
        if 'fnmatch' in filter_rule:
            col_dat = df_sum.apply(_categorize_fn,axis=1,args=(filter_rule['parm'],filter_rule['fnmatch'],filter_rule.get('no_match',None)))
            df_sum[new_parm] = col_dat
        
        elif 'regex' in filter_rule:
            col_dat = df_sum.apply(_categorize_re,axis=1,args=(filter_rule['parm'],filter_rule['regex'],filter_rule.get('no_match',None)))
            df_sum[new_parm] = col_dat

        elif 'callable' in filter_rule:
            col_dat = df_sum[filter_rule['parm']].apply(filter_rule['callable'])
            df_sum[new_parm] = col_dat


def _categorize_fn(row,parm,rules,no_match=None):
    """returns the key of rules if any of its test match, otherwise returns no_match"""
    value = row[parm].strip().lower()
    for set_val, tests in rules.items():
        for test in tests:
            if fnmatch.fnmatch(value,test):
                return set_val
    return no_match

def _categorize_re(row,parm,rules,no_match=None):
    """returns the key of rules if any of its test match, otherwise returns no_match"""    
    value = row[parm].strip().lower()
    for set_val, tests in rules.items():
        for test in tests:
            regexp = re.compile(test)
            if regexp.search(value):
                return set_val
    return no_match


def plot_summary(df_sum,ignore_parms=['bouy','spring']):
    """creates a summary plot of TS vs Hs of each test by title"""

    log.info(f'plotting summary to: {results_dir}')

    fig,ax = subplots(figsize=(10,10))
    for title,dfs in df_sum.groupby('title'):
        if not any([t in  title.lower() for t in ignore_parms]):
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
        if not any([t in  title.lower() for t in ignore_parms]):
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
        run_id = dat['run_id']
        df = dat['df']
        L = df.iloc[0]
        hs = L['hs']
        ts = L['ts']
        case = L['title']

        title = f'Run {run_id}: {case} | Hs: {hs:5.4f} Ts: {ts:5.4f}'
        print(f'plotting {title} from {inpt} inpt: {dat["input"]["data"]["title"]}')

        case_dir = os.path.join(results_dir,case.replace('-','_').strip())
        os.makedirs(case_dir,exist_ok=True,mode=754)
        #df.to_csv(os.path.join(case_dir,f'run_{i}.csv'))
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
        fig.savefig(os.path.join(case_dir,f'run_{run_id}.png'))
        close('all')

def get_run_data(df_sum,run_id):
    try:
        title = df_sum['title'].iloc[run_id]
        case = title.replace('-','_').strip()
        path = os.path.join(results_dir,case,f'run_{run_id}.csv')
        print(f'getting: {title} | run: {run_id}')
        notes = df_sum['notes'].iloc[run_id]
        if 'nan' != str(notes):
            print(f'notes: {notes}')
        return pd.read_csv(path)
    except Exception as e:
        print(f'couldnt get run: {run_id}| {e}')
        return None


def diff_values(zz):
    bcoef, acoef = signal.butter(3, 0.01)

    v = np.concatenate(([0],np.diff(zz)))
    a = np.concatenate(([0],np.diff(v)))
    
    ac_max = np.nanmax(np.abs(a))
    vc_max = np.nanmax(np.abs(v))
    
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
            close('all')
        except Exception as e:
            print(f'error: {e}|\n{traceback.print_tb(e.__traceback__)}')

    df_sum.to_csv(os.path.join(results_dir,f'summary.csv'),index=False)

def process_run(df_sum,run_id,u_key='z_wave',plot=False):
    """provided the summary dataframe and the index id, gather dataframe and analyze"""

    rec = df_sum.iloc[run_id]
    dfr = get_run_data(df_sum,run_id)
    if dfr is None:
        return None

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
        

    zrel_vel,zrel_acc,zrel_wght= diff_values(dfr['z2'])
    zrel_pos = np.average(dfr['z2'],weights=zrel_wght)
    zrel = dfr['z2'] - zrel_pos

    if no_z1:    
        z2_vel,z2_acc,z2_wght= diff_values(dfr['z2'])
        z2_pos = np.average(dfr['z2'],weights=z2_wght)
        z2 = zrel
    else:
        z2_vel,z2_acc,z2_wght= diff_values(dfr['z2_abs'])
        z2_pos = np.average(dfr['z2_abs'],weights=z2_wght)
        z2 = dfr['z2_abs'] - z2_pos        

    a2 = dfr['az'] - dfr['az'].mean()
    
    key = 'z_wave'
    hs = rec['hs']
    dh_max = (dfr[key].max() - dfr[key].min())
    if dh_max > 0:
        scale = 1000 * hs/dh_max
    else:
        scale = 1000

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

    #Max Filter Analysis
    dt = np.maximum(np.median(np.diff(time)),0.0001)
    N_osll = int(rec['ts']/dt)
    tm_roll = stld.sliding_window_view(tm,N_osll).max(axis=1)
    zf_hmax = stld.sliding_window_view(xf,N_osll).max(axis=1)
    zf_hmin = stld.sliding_window_view(xf,N_osll).min(axis=1)
    hs_zf = zf_hmax - zf_hmin

    #Check On Time When HsZf > 0
    is_act = (hs_zf > 0).astype(int)
    switch = np.array([0]+np.diff(is_act).tolist())
    on_times = tm_roll[switch > 0]
    off_times = tm_roll[switch < 0]

    #Find Valid Time Ranges
    time_sels = {}
    if len(off_times) and len(on_times):
        for offt in off_times:
            dt_cans = offt-on_times
            dt_inx = dt_cans > 0
            if np.any(dt_inx):
                dt_min = (dt_cans[dt_inx]).min()
                if not np.isnan(dt_min):
                    inx_min = np.where(dt_cans==dt_min)[0]
                    on_time = on_times[inx_min][0]
                    time_sels[dt_min] = (on_time,offt)

    is_wave_motion = False
    if len(time_sels) > 0 and max(time_sels.keys()) > 30:
        is_wave_motion = True
        run_time = max(time_sels.keys())
        on_time,off_time = time_sels[run_time]
        time_mask = np.logical_and(time>=on_time-1,time<=off_time+1)

    else:
        time_mask = np.ones(time.shape)==1
    
    #Resample To Largest Contigious Input Time
    tm = time = time[time_mask]
    xf = xf[time_mask]
    z1 = x1 = z1[time_mask]
    z2 = x2 = z2.to_numpy()[time_mask]
    v1 = z1_vel[time_mask]
    v2 = z2_vel[time_mask]
    a1 = a1[time_mask]
    a2 = a2[time_mask]

    diff_z1 = np.diff(z1)
    diff_z2 = np.diff(z2)

    x_rel = zrel[time_mask]
    v_rel = zrel_vel[time_mask]
    a_rel = zrel_acc[time_mask]
    
    tm_roll = stld.sliding_window_view(time,N_osll).max(axis=1)
    zf_hmax = stld.sliding_window_view(xf,N_osll).max(axis=1)
    zf_hmin = stld.sliding_window_view(xf,N_osll).min(axis=1)
    z1_hmax = stld.sliding_window_view(x1,N_osll).max(axis=1)
    z1_hmin = stld.sliding_window_view(x1,N_osll).min(axis=1)
    z2_hmax = stld.sliding_window_view(x2,N_osll).max(axis=1)
    z2_hmin = stld.sliding_window_view(x2,N_osll).min(axis=1)     
    xr_hmax = stld.sliding_window_view(x_rel,N_osll).max(axis=1)
    xr_hmin = stld.sliding_window_view(x_rel,N_osll).min(axis=1)
    
    hs_zf = zf_hmax - zf_hmin
    hs_z1 = z1_hmax - z1_hmin
    hs_z2 = z2_hmax - z2_hmin
    hs_xr = xr_hmax - xr_hmin

    

    hinx = hs_zf >= 1
    h2f_ratio = hs_z2[hinx]/hs_zf[hinx]
    h1f_ratio = hs_z1[hinx]/hs_zf[hinx]
    xrf_ratio = hs_xr[hinx]/hs_zf[hinx]
    hs_zf_med = np.median(hs_zf[hinx])
    h2f_med = np.median(h2f_ratio)
    h1f_med = np.median(h1f_ratio)
    xrf_med = np.median(xrf_ratio)
    hs_zf_avg = np.nanmean(hs_zf[hinx])
    h2f_avg = np.nanmean(h2f_ratio)
    h1f_avg = np.nanmean(h1f_ratio)
    xrf_avg = np.nanmean(xrf_ratio)
    hs_zf_std = np.nanstd(hs_zf[hinx])
    h2f_std = np.nanstd(h2f_ratio)
    h1f_std = np.nanstd(h1f_ratio)
    xrf_std = np.nanstd(xrf_ratio)    

    #zero cross estimate
    zc_time = x1[:-1]*x1[1:]
    zc_times = (time[1:][zc_time <= 0])
    dt_zc = np.diff(zc_times).mean()
    ts_est = dt_zc*2

    #data is valid if some z2 motion
    z2_rel = np.median(np.abs(np.diff(x2)))
    is_rel_motion = z2_rel > 0

    #Check for spikes
    has_spikes1 = np.any(np.abs(diff_z1) >  xrf_ratio.max()*0.75)
    has_spikes2 = np.any(np.abs(diff_z2) >  xrf_ratio.max()*0.75)
    has_spikes = has_spikes1 or has_spikes2

    #check for timegaps
    dt_max = np.diff(time).max()
    has_gaps = dt_max > 1


    #zref diff check to ensure motiono
    valid_data = not np.isnan(xrf_med) and is_wave_motion and is_rel_motion

    #items in analysis_kw are added to summary if they are int/float/bool
    analysis_kw = dict(
    run_id=run_id,
    N_osll = N_osll,
    tm_roll = tm_roll,
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
    h2f_med = h2f_med,
    h2f_avg = h2f_avg,
    h2f_std = h2f_std,    
    h1f_med = h1f_med,
    h1f_avg = h1f_avg,
    h1f_std = h1f_std,
    xrf_med = xrf_med,
    xrf_avg = xrf_avg,
    xrf_std = xrf_std,
    hs_zf_std=hs_zf_std,
    hs_zf_avg=hs_zf_avg,
    hs_zf_med=hs_zf_med,
    toff=toff,
    dt=dt,
    omg=wave_omg,
    has_gaps = int(has_gaps),
    has_spikes = int(has_spikes),
    valid_data = int(valid_data),
    dof_3d=int(no_z1 and valid_data) 
    )

    for k,v in analysis_kw.items():
        if isinstance(v,(float,int,bool)):
            if k not in df_sum:
                df_sum[k] = None
            df_sum.loc[run_id,k] = v


    fig,ax = None,None
    if plot:
        fig,(ax,ax2) = subplots(nrows=2,figsize=(20,10),sharex=True)
        ax.scatter(tm,x1,c='m',label='z1',alpha=0.7,s=1)
        ax.plot(tm,x1,'m',alpha=0.5)
        ax.plot(tm_roll,z1_hmax,'m--',alpha=0.25)
        ax.plot(tm_roll,z1_hmin,'m--',alpha=0.25)
        ax.scatter(tm,z2,c='c',label='z2',alpha=0.7,s=1)
        ax.plot(tm,x2,'c',alpha=0.5)
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

    time = time.to_numpy()

    out = dict(z1=x1,z2=x2,v1=v1,v2=v2,xf=xf,a1=a1,a2=a2,df=dfr,rec=rec,time=time,z_act=z_act,toff=toff,fig=fig,ax=ax,dof_3d=no_z1,dt=dt,x_rel=x_rel,v_rel=v_rel,a_rel=a_rel,omg=wave_omg,ts=rec['ts'],hs=rec['hs'],analysisKw=analysis_kw)

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
    parser.add_argument('-PRPD','--process-plot', help='run processing plots',**kwarg)
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
        do_plot = args.process_plot or args.run_all
        process_runs(df_sum,plot=do_plot)

    if args.pl_sum or args.run_all:
        plot_summary(df_sum)

    if data and (args.plot_data or args.run_all):
        plot_data(data['data'])

    return data,df_sum


if __name__ == '__main__':

    out,df_sum = main()    








