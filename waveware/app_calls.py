import datetime

import dash
from dash import dcc, html, dash_table
import dash_daq as daq

from waveware.config import *
from waveware.app_comps import *
from dash.dependencies import Input, Output,State
import sys

import time
import plotly
import plotly.express as px
import numpy as np
import pandas as pd
pd.options.plotting.backend = "plotly"

log.info(sys.executable)
import logging
import requests

from decimal import *

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dashboard")

POLL_INTERVAL = 1.0

external_stylesheets = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]



@app.callback(
    [Output(f'{mk}-graph',"figure") for mk in PLOTS],
    Input("graph-update","n_intervals"),
    State("daq_on_off","on")
            )
def update_graphs(n,on):
    """first ask for new data then update the graphs"""
    log.info(f'update graphs {on}')
    begin = time.perf_counter()
    if on:
        try:
            if memcache:
                #we got data so lets do the query
                max_ts = max(list(memcache.keys()))
                new_data = requests.get(f"{REMOTE_HOST}/getdata?after={max_ts}")
            else:
                #no data, so ask for the full blast. yeet
                new_data = requests.get(f"{REMOTE_HOST}/getdata")



            #Apply away
            if new_data.status_code == 200:
                #log.info(f'got response {new_data}')
                data = new_data.json()
                #add data to cache
                for ts,data in data.items():
                    memcache[float(ts)] = data
            else:
                log.info(f'got bad response: {new_data}')

            tm = time.perf_counter()        
            df = pd.DataFrame.from_dict(list(memcache.values()))
            #adjust to present
            df['timestamp']=df['timestamp']-tm

            fig_pr = px.scatter(df,x='timestamp',y=z_sensors)#trendline='lowess',trendline_options=dict(frac=1./10.))
            fig_pr.update_layout({
            "plot_bgcolor": "rgba(0, 0, 0, 0)",
            "paper_bgcolor": "rgba(0, 0, 0, 0)",
            "font_color":"white",
            })        
            fig_pr.update_xaxes({
                "linecolor":"white",
                "gridcolor":"white"
                }) 

            fig_speed = plotly.express.line(df,x='timestamp',y=e_sensors)
            fig_speed.update_layout({
            "plot_bgcolor": "rgba(0, 0, 0, 0)",
            "paper_bgcolor": "rgba(0, 0, 0, 0)",
            "font_color":"white",
            })
            fig_speed.update_xaxes({
                "linecolor":"white",
                "gridcolor":"white"
                })        

            fig_alph = plotly.express.line(df,x='timestamp',y=z_wave_parms)
            fig_alph.update_layout({
            "plot_bgcolor": "rgba(0, 0, 0, 0)",
            "paper_bgcolor": "rgba(0, 0, 0, 0)",
            "font_color":"white",
            })
            fig_alph.update_xaxes({
                "linecolor":"white",
                "gridcolor":"white"
                })
                    
            log.info(f'returning 3 graphs {time.perf_counter()-begin}')
            return [fig_pr,fig_speed,fig_alph]
        
        except Exception as e:
            log.error(e,exc_info=1)
            log.info(e)
    
    raise dash.exceptions.PreventUpdate


#all_sys_vars get update in order by data
@app.callback(
    [Output(f'{parm}-display',"value") for parm in all_sys_vars],
    Input("num-raw-update","n_intervals"),
    State("daq_on_off","on")
    )

def update_readout(n,on):
    if on:
        log.info(f'update readout: {on}')
        try:
            new_data = requests.get(f"{REMOTE_HOST}/getcurrent")
            data = new_data.json()
            if data:
                data= [float(Decimal(data[k]).quantize(mm_accuracy_ech)) if k in e_sensors else float(Decimal(data[k]).quantize(mm_accuracy_enc)) for k in all_sys_vars]
                return data

            raise dash.exceptions.PreventUpdate

        except Exception as e:
            log.error(f'update issue: {e}',exc_info=1)
    
    raise dash.exceptions.PreventUpdate


@app.callback(Output("daq_on_off", "label"),
              Input("daq_on_off", "on"),
              prevent_initial_call=True)
def turn_on_off_daq(on):
    log.info(f"setting {on}.")
    if on:
        requests.get(f"{REMOTE_HOST}/turn_on")
        return "DAC ON"
    else:
        requests.get(f"{REMOTE_HOST}/turn_off")
        return "DAC OFF"
    
@app.callback(Output("motor_on_off", "label"),
              Input("motor_on_off", "on"),
              prevent_initial_call=True)
def dis_and_en_able_motor(on):
    log.info(f"setting {on}.")
    if on:
        requests.get(f"{REMOTE_HOST}/control/enable")
        return "MOTOR ENABLED"
    else:
        requests.get(f"{REMOTE_HOST}/control/disable")
        return "MOTOR DISABLE"
    
@app.callback(Output('mode-select','value'),
              Input("radio-button", "n_clicks"))
def stop_motor(n_clicks,console):
    log.info(f"stopping {n_clicks}.")
    if n_clicks < 1:
        return
    resp = requests.get(f"{REMOTE_HOST}/control/stop")
    if resp.status_code  == 200:
        return 0 #set off
    else:
        return 0




#LOGGING FUNCTIONS
@app.callback(Output('console','children',allow_duplicate=True),
              Input("zero-btn", "n_clicks"),
              State('console','children'),
              prevent_initial_call=True)
def zero_sensors(n_clicks,console):
    log.info(f"zeroing {n_clicks}.")
    if n_clicks < 1:
        return
    resp = requests.get(f"{REMOTE_HOST}/hw/zero_pos")
    if resp.status_code  == 200:
        return append_log(console,resp.text,'ZEROING')
    else:
        return append_log(console,f'ERROR ZEROING: {resp.status_code}|{resp.text}')

@app.callback(
    Output('console','children',allow_duplicate=True),
    Output('test-log','children'),
    Input("calibrate-btn","n_clicks"),
    State('console','children'),
    State('test-log','children'),
    prevent_initial_call=True
)
def log_note(btn,console,test_msg):
    """requests calibrate and prints the response:"""
    resp = requests.post(f'{REMOTE_HOST}/log_note',data=str(test_msg))
    cons = append_log(console,resp.text,'LOGGED NOTE')
    return cons,'' #empty log text to signify its sent
        
def append_log(prv_msgs,msg,section_title=None):
    b = []
    title = None
    if prv_msgs:
        b = [ html.P(v) for v in prv_msgs.replace('<p>','').split('</p>') ]
    if section_title:
        title = section_title
        spad = int((80-len(title)/2))
        title = html.P('#'*spad+' '+title.upper()+' '+'#'*spad)

    if msg:
        log.info(msg)
        top = html.P(msg) if isinstance(msg,str) else msg
        if title:
            b = [title,top,html.P('#'*80)]+b[:1000]
        else:
            b = [top]+b[:1000]
        
    return html.Div(b)

   

#TODO: setup inputs callbacks
# @app.callback(
#     Output("title-in-input","value"),
#     Output("sen1-x-input","value"),
#     Output("sen1-rot-input","value"),
#     Output("sen2-x-input","value"),    
#     Output("sen2-rot-input","value"),
#     Output("air-pla-input","value"),
#     Output("water-pla-input","value"),
#     Input("reset-btn","n_clicks"),
#     )
# def reset_labels(btn):
#     out = requests.get(f"{REMOTE_HOST}/reset_labels")
#     data = out.json()
# 
#     return [data['title'],data['sen1-x'],data['sen1-rot'],data['sen2-x'],data['sen2-rot'],data['air-pla'],data['water-pla']]

#TODO: set meta parms and/or edit table here (outy ect)
# @app.callback(
#     Output("hidden-div",'children'),
#     Input("set-btn","n_clicks"),
#     State("title-in-input","value"),
#     prevent_initial_call=True
#     )
# def set_labels(btn,title,sen1x,sen1rot,sen2x,sen2rot,airpla,waterpla):
#     
#     resp = requests.get(f"{REMOTE_HOST}/set_labels?title={title}&sen1-x={sen1x}&sen1-rot={sen1rot}&sen2-x={sen2x}&sen2-rot={sen2rot}&air-pla={airpla}&water-pla={waterpla}")
# 
#     out = resp.text
# 
#     return out



#TODO: replace states  
# State("sen1-x-input","value"),
# State("sen1-rot-input","value"),
# State("sen2-x-input","value"),    
# State("sen2-rot-input","value"),
# State("air-pla-input","value"),
# State("water-pla-input","value"),


