# from piplates import DACC

import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash
from dash import ctx, no_update
from dash import dcc, html, dash_table
import dash_daq as daq

from waveware.config import *
from waveware.data import *
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
import json
from decimal import *

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dashboard")

POLL_INTERVAL = 1.0

external_stylesheets = ["https://codepen.io/chriddyp/pen/bWLwgP.css"]

app = dash.Dash(
    __name__,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"}
    ],
    external_stylesheets=external_stylesheets,
)
app.title = TITLE = "WAVE TANK DASHBOARD"
app.layout = DASH_LAY


def control_status():
    resp = requests.get(f"{REMOTE_HOST}/control/status")
    return resp.json()

def format_value(k,data):
    if data:
        if k in e_sensors:
            return float(Decimal(str(data)).quantize(mm_accuracy_ech))
        else:
            return float(Decimal(str(data)).quantize(mm_accuracy_enc))
    return data




#TODO; add status (indicator?) output red/green for true/false
#all_sys_vars get update in order by data
@app.callback(
    [Output(f'{parm}-display',"value") for parm in all_sys_vars],
    Input("num-raw-update","n_intervals"),
    State("daq_on_off","on")
    )

def update_readout(n,on):
    if on:
        log.info(f'update readout: {on}')
        new_data = None
        try:
            new_data = requests.get(f"{REMOTE_HOST}/getcurrent")
            if new_data.status_code == 420:
                raise dash.exceptions.PreventUpdate
            
            data = new_data.json()
            if data:
                data= [ format_value(k,data[k]) if k in data else 0 for k in all_sys_vars]
                return data
        except dash.exceptions.PreventUpdate:
            pass #continue to your demise!
        except Exception as e:
            log.error(f'update issue: {e}',exc_info=1)
    
    raise dash.exceptions.PreventUpdate


#ASSIGNMENT CALLS
#MAJOR IO (DATA/ MOTOR ENABLE)
#we need to handle all status at the same time since we call the machine to check, easier to set at same time
@app.callback( Output('console','value',allow_duplicate=True),
               Output("motor_on_off", "on"),
               Output("motor_on_off", "label"),
               Output("daq_on_off", "on"),
               Output("daq_on_off", "label"),               
               Input("num-raw-update","n_intervals"), #on timer
               Input("motor_on_off", "on"),
               Input("daq_on_off", "on"),
               State("motor_on_off", "on"),
               State("daq_on_off", "on"),
               State('console','value'),
               prevent_initial_call=True)
def update_status(n,m_on_new,d_on_new,m_on_old,d_on_old,console):
    """if input is != state then we know a user provided input, if input != current status then call to system should be made to set state
    
    care should be taken to alighn to the machines end state, which means not taking user triggered action IF the net result would be the machine ending in current state.
    """

    #the output of this call should expect to not have an update
    new = [m_on_new,d_on_new]
    current = [m_on_old,d_on_old]
    
    
    triggers = [t["prop_id"] for t in ctx.triggered]

    #get true status
    status = control_status()
    if 'num-raw-update.n_intervals' not in triggers:
        log.info(f'got status: {status} for triggers: {triggers}')
        log.info(f'new: {new} current: {current}')

    mode = status['drive_mode']
    mode = mode if mode.lower() != 'cal' else 'center'
    mode_id = wave_drive_modes.index(mode.lower())
    motor_on = not status['motor_stopped']
    dac_on = status['dac_active']

    actions = [] #for console


    #Prep output
    out = [no_update for i in range(5)]


    user_input = False
    if 'motor_on_off.on' in triggers:
        #set the motor state to desired if not already
        if m_on_new != motor_on:
            user_input = True
            if m_on_new:
                actions.append('Enabled Motor')
                requests.get(f"{REMOTE_HOST}/control/enable")
                out[1] = True
                out[2] = "Motor Enabled"
            else:
                actions.append('Disabled Motor')
                requests.get(f"{REMOTE_HOST}/control/disable")
                out[1] = False
                out[2] = "Motor Disabled"
        elif motor_on != m_on_old:
            # a simple interface change
            if motor_on:
                out[3] = True
                out[4] = "DAC Enabled"
            else:
                out[3] = False
                out[4] = "DAC Disabled"                

    if 'daq_on_off.on' in triggers:
        #set dac status to desired if not already
        if d_on_new != dac_on:
            user_input = True
            if d_on_new:
                actions.append('DAC ON')
                requests.get(f"{REMOTE_HOST}/turn_on")
                out[3] = True
                out[4] = "DAC Enabled"
            if not d_on_new:
                actions.append('DAC OFF')
                requests.get(f"{REMOTE_HOST}/turn_off")
                out[3] = False
                out[4] = "DAC Disabled"

    if not user_input and 'num-raw-update.n_intervals' in triggers:
        #update the items per control status
        if motor_on and not m_on_old:
            actions.append(f'updt: motor engaged')
            out[1] = True
            out[2] = "Motor Enabled"
        elif not motor_on and m_on_old:
            actions.append(f'updt: motor disabled')
            out[1] = False
            out[2] = "Motor Disabled"            

        if dac_on and not d_on_old:
            actions.append(f'updt: dac engaged')
            out[3] = True
            out[4] = "DAC Enabled"

        elif not dac_on and d_on_old:
            actions.append(f'updt: dac disabled')
            out[3] = False
            out[4] = "DAC Disabled"  

    if DEBUG and actions:
        log.info(f'update status: {status} for triggers: {triggers} | actions: {actions}')

    #TODO: final check?   
    #elif user_input:
    #    #check status again after calls
    #    status = control_status()

    if actions:
        console = append_log(console,actions)
        out[0] = console

    #finally set values based on status if it is different
    if user_input and DEBUG:
        log.info(f'actions: {actions} setting out: {out}')
    return out


#Set Drive Mode:
fixed_order = ['console','mode','title','tb_data']
Nfo = len(fixed_order)
order = fixed_order+list(wave_input_parms)
@app.callback( Output('console','value'),
               Output("mode-select", "value"),              
               Output("title-in", "value"),
               Output('edit-control-table','data'),
               [Output(f'{k}-input','value') for k in wave_input_parms],
               Input("drive-refresh", "n_clicks"),
               Input("drive-set-exec", "n_clicks"),
               State("mode-select", "value"),
               State("title-in", "value"),
               State('console','value'),
               State("motor_on_off", "on"),
               State('edit-control-table','data'),
               [State(f'{k}-input','value') for k in wave_input_parms])

def update_control(n_clk,g_int,ms_last,title_in,console,motor_on,tb_data,*wave_input):
    """When the drive-set-exec button is pressed, all state is sent to server, 
    If 200 response, data is set otherwise error is logged.
    """
    triggers = [t["prop_id"] for t in ctx.triggered]

    #log.info(f'args for trigger: {triggers}')
    #log.info(n_clk,g_int,ms_last,title_in,*wave_input)

    #by default all changes will be nothing!
    output = [no_update]*(Nfo+len(wave_input_parms))

    #get state from wave input
    st_parms = {k:w for k,w in zip(wave_input_parms,wave_input)}
    st_parms['title'] = title_in
    st_parms['mode'] = ms_last

    #separte edit field parameters
    tb_data = {d['key']:d['val'] for d in tb_data}
    ed_parms = {}
    for ed_in in edit_inputs:
        if ed_in in st_parms:
            ed_parms[ed_in] = st_parms.pop(ed_in)

    #make call to control status
    current = requests.get(f'{REMOTE_HOST}/control/get')
    if current.status_code == 200:
        pkg = current.json()
        rm_parms = {k:v for k,v in pkg.items()}
    else:
        log.info(f'bad rmt response: {current.text}')
        raise dash.exceptions.PreventUpdate
  

    if ('drive-refresh.n_clicks' in triggers and len(triggers) == 1) or not motor_on or len(triggers) == 0:
        if 'drive-refresh.n_clicks' not in triggers:
            output[0] = append_log(console,'Must Enable Motor!')
            output[1] = 'STOP'
        #check embedded device state and set output reflecting embedded
        
        #check updates    
        updates = {}
        for k,cval in rm_parms.items():
            if k in st_parms:
                st = st_parms[k]
                if st != cval:
                    updates[k] = cval
            if k in ed_parms:
                if k in tb_data:
                    tb_data[k] = cval
                    output[Nfo-1] = tb_data #keep updating is fine same ref...
                else:   
                    updates[k] = cval #others
            elif k not in ed_parms:
                log.info(f'missing status: {k}')  

        if updates:
            log.info(f'got updates: {updates}| {ed_parms}')
            for k,v in updates.items():
                output[order.index(k)] = v

        o = {k:v for k,v in zip(order,output) if v is not no_update}
        if DEBUG:
            log.info(f'setting output: {o} from {output}')

        #mode special case
        if output[1] is not no_update:
            new = output[1].strip().upper()            
            print(f'upper for mode: {new}')
            output[1] = new

        return output
    
    #otherwise it was a click!
    if 'drive-set-exec.n_clicks' in triggers:
        #update
        log.info(f'updating with: {st_parms}| {tb_data} | {ed_parms}')

        #check updates    
        updates = st_parms.copy()
        updates.update(tb_data)
        updates.update(ed_parms)

        #set the data and record result to console
        updates.update(tb_data)
        log.info(f'set updates: {updates}')
        resp = requests.post(f'{REMOTE_HOST}/control/set',
                      data=json.dumps(updates))
        if resp.status_code == 200:
            output[0] = append_log(console,f'Successfuly Set: {updates}')
        else:
            output[0] = append_log(console,f'Issue Setting Wave: {resp.text}')

        #mode special case
        if output[1] is not no_update:
            new = output[1].strip().upper()            
            print(f'upper for mode: {new}')
            output[1] = new

        return output

    raise dash.exceptions.PreventUpdate

#Save Table Config
@app.callback(
    Output('console','value',allow_duplicate=True),
    Input('cntl-vals-save','n_clicks'),
    State('console','value'),
    State('edit-control-table','data'),
    prevent_initial_call=True
)
def save_config(n_clicks,console,tb_data):
    
    updates = {d['key']:d['val'] for d in tb_data}

    log.info(f'set updates: {updates}')
    resp = requests.post(f'{REMOTE_HOST}/save_table_config',
                    data=json.dumps(updates))
    
    if resp.status_code == 200:
        output = append_log(console,f'Successfuly Set: {updates}')
    else:
        output = append_log(console,f'Issue Setting Wave: {resp.text}')

    return output



### CALLS & UTILITY FUNCTIONS
#EStop
@app.callback(Output('console','value',allow_duplicate=True),
              Input("stop-btn", "n_clicks"),
              State("motor_on_off", "on"),
              State('console','value'),
              prevent_initial_call=True)
def stop_motor(n_clicks,on,console):
    log.info(f"stopping {n_clicks}.")
    if n_clicks is None or n_clicks < 1:
        return
    status = control_status()
    if on or not status['motor_stopped']:
        resp = requests.get(f"{REMOTE_HOST}/control/stop")
        if resp.status_code  == 200:
            o = 'Motor Stopped' #set off
        else:
            o = f'Error Stopping: {resp.status_code}|{resp.text}'
    else:
        o = 'Already Stopped'

    return append_log(console,o)

#Zero Cals
@app.callback(Output('console','value',allow_duplicate=True),
              Input("zero-btn", "n_clicks"),
              State('console','value'),
              prevent_initial_call=True)
def zero_sensors(n_clicks,console):
    log.info(f"zeroing {n_clicks}.")
    if n_clicks is None or  n_clicks < 1:
        return
    resp = requests.get(f"{REMOTE_HOST}/hw/zero_pos")
    if resp.status_code  == 200:
        return append_log(console,resp.text,'ZEROING')
    else:
        return append_log(console,f'ERROR ZEROING: {resp.status_code}|{resp.text}')

#MPU_Calibrate
@app.callback(
    Output('console','value',allow_duplicate=True),
    Output('test-log','value'),
    Input("test-log-send","n_clicks"),
    State('console','value'),
    State('test-log','value'),
    prevent_initial_call=True
)
def log_note(btn,console,test_msg):
    """requests calibrate and prints the response as raw text"""

    log.info(f'GOT LOG: {test_msg}')

    body = {
        'test_log': test_msg,
        'sys_status': control_status(),
        'at': str(datetime.datetime.now(tz=pytz.utc))
        #more info added at state
    }

    resp = requests.post(f'{REMOTE_HOST}/log_note',data=json.dumps(body))
    cons = append_log(console,resp.text,'LOGGED NOTE')
    return cons,'' #empty log text to signify its sent
        
def append_log(prv_msgs,msg,section_title=None):
    b = []
    title = None

    if isinstance(prv_msgs,str):
        b = prv_msgs.split('\n')
    else:
        log.info(f'unknown prv: {prv_msgs}')
        

    if section_title:
        title = section_title
        spad = int((20-len(title)/2))
        title = '#'*spad+' '+title.upper()+' '+'#'*spad

    if msg:
        if isinstance(msg,(list,tuple)):
            msg = '\n'.join(msg)
        log.info(msg)
        top = msg
        if title:
            b = [title,top,'#'*20]+b[:1000]
        else:
            b = [top]+b[:1000]
    

    out = '\n'.join(b)
    return out

def de_prop(prv_msgs,dflt):
    if isinstance(prv_msgs,str):
        return prv_msgs
    if prv_msgs is None:
        return ''   
    if isinstance(prv_msgs,dict):
        p = prv_msgs.get('props',{})
    else:
        raise Exception(f'unexpected {prv_msgs}')
    return p.get('children',dflt)



axes_style = {
                "linecolor":"white",
                "gridcolor":"white"
                }
layout_style = {
            "plot_bgcolor": "rgba(0, 0, 0, 0)",
            "paper_bgcolor": "rgba(0, 0, 0, 0)",
            "font_color":"white",
            }



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
            #TODO: add synchronization via diskcache... in background thread?
            if memcache:
                #we got data so lets do the query
                max_ts = max(list(memcache.keys()))
                new_data = requests.get(f"{REMOTE_HOST}/getdata?after={max_ts}")
            else:
                #no data, so ask for the full blast. yeet
                new_data = requests.get(f"{REMOTE_HOST}/getdata")

            #Apply away
            if new_data.status_code == 420:
                raise dash.exceptions.PreventUpdate

            if new_data.status_code == 200:
                data = new_data.json()
                #add data to cache
                for ts,data in data.items():
                    memcache[float(ts)] = data
            else:
                log.info(f'got bad response: {new_data}')

            #dataframe / index
            #tm = time.perf_counter()    
            data = list(memcache.values())
            df = pd.DataFrame.from_dict(data)

            df.set_index('timestamp')
            df.sort_index()

            #adjust to present
            
            t = df['timestamp']
            df['timestamp']=t-t.max()

            fig_pr = px.scatter(df,x='timestamp',y=z_sensors)#trendline='lowess',trendline_options=dict(frac=1./10.))
            fig_pr.update_layout(layout_style)
            fig_pr.update_xaxes(axes_style)

            fig_speed = plotly.express.line(df,x='timestamp',y=e_sensors)
            fig_speed.update_layout(layout_style)
            fig_speed.update_xaxes(axes_style)        

            fig_zv = plotly.express.line(df,x='timestamp',y=zgraph)
            fig_zv.update_layout(layout_style)
            fig_zv.update_xaxes(axes_style)      

            fig_vv= plotly.express.line(df,x='timestamp',y=vgraph)
            fig_vv.update_layout(layout_style)
            fig_vv.update_xaxes(axes_style)              
                                
            log.info(f'returning 3 graphs {time.perf_counter()-begin}')
            return [fig_zv,fig_vv,fig_pr,fig_speed]
        
        except dash.exceptions.PreventUpdate:
            pass

        except Exception as e:
            log.error(e,exc_info=1)
            log.info(e)
    
    raise dash.exceptions.PreventUpdate



# Function to fetch data from the endpoint
def fetch_data():
    response = requests.get('http://localhost:8777/run_summary')
    if response.status_code == 200:
        data = response.json()
        df = pd.DataFrame.from_dict(data, orient='index')
        df.rename(columns={'index': 'run_id'}, inplace=True)
        print(df)
        return df
    else:
        return pd.DataFrame(columns=['run_id', 'title', 'Ts', 'Hs', 'Hf'])

# Callback to update the data
@app.callback(
    [Output('data-table', 'data'),
     Output('x-parm-id', 'options'),
     Output('y-parm-id', 'options')],
    [Input('summary-update', 'n_intervals')]
)
def update_data(n_intervals):
    df = fetch_data() 
    data = df.to_dict('records')
    runs = pd.unique(df['title'])
    dropdown_options = [{'label': str(run_id), 'value': run_id} 
                                  for run_id in runs]
    #dropdown_options,
    return data,  df.columns,df.columns

# Callback to update the scatter plot based on filters
@app.callback(
    Output('results-plot-graph', 'figure'),
    [Input('hs-range-slider', 'value'),
     Input('ts-range-slider', 'value'),
     Input('run-title-input', 'value'),
     Input('x-parm-id', 'value'),
     Input('y-parm-id', 'value')],     
    [State('data-table', 'data')]
)
def update_scatter_plot( hs_range, ts_range, title_filter,xparm,yparm, data):
    if not data:
        raise dash.PreventUpdate
    
    df = pd.DataFrame(data)
    if hs_range:
        df = df[(df['Hs'] >= hs_range[0]) & (df['Hs'] <= hs_range[1])]
    if ts_range:
        df = df[(df['Ts'] >= ts_range[0]) & (df['Ts'] <= ts_range[1])]
    if title_filter:
        df = df[df['title'].str.contains(title_filter, case=False, na=False)]

    fig = px.line(df, x=xparm, y=yparm, color='title', title=f'Scatter Plot of {xparm} vs {yparm}')
    fig.update_layout(
        plot_bgcolor='#001f3f',
        paper_bgcolor='#001f3f',
        font_color='#ffffff',
        legend=dict(
            bgcolor='#001f3f',
            font=dict(color='#ffffff')
        ),
        xaxis=dict(tickfont=dict(color='#ffffff')),
        yaxis=dict(tickfont=dict(color='#ffffff')),
        
    )
    return fig







def main():
    """runs the dash / plotly process"""
    import os

    
    try:

        log.info(f'serving dashboard on: {FW_HOST} with DEBUG={DEBUG}')

        #FIXME: debug can cause zombie processes, thanks 70k per year software!
        #You can sometimes change this with PORT env var
        #On WSL zombies can permanently hang causing weird networking issues
        app.run_server(debug=DEBUG,host=FW_HOST)

    except KeyboardInterrupt:
        sys.exit()


if __name__ == "__main__":


    main()























































#         html.Div(id='live-update-text'),
#         dcc.Graph(id='live-update-graph'), #TODO: define timeseries
#
#         #FOOTER
#         # dcc.Interval(
#         #     id='interval-component',
#         #     interval=1*1000, # in milliseconds
#         #     n_intervals=0
#         # )


# @app.callback(Output('live-update-text', 'children'),
#               Input('interval-component', 'n_intervals'))
# def update_metrics(n):
#     pass
#
#
# # Multiple components can update everytime interval gets fired.
# @app.callback(Output('live-update-graph', 'figure'),
#               Input('interval-component', 'n_intervals'))
# def update_graph_live(n):
#     pass


#
# dcc.Graph(
#     id="wind-direction",
#     figure=dict(
#         layout=dict(
#             plot_bgcolor=app_color["graph_bg"],
#             paper_bgcolor=app_color["graph_bg"],
#         )
#     ),
# ),

# dcc.Graph(
#     id="wind-histogram",
#     figure=dict(
#         layout=dict(
#             plot_bgcolor=app_color["graph_bg"],
#             paper_bgcolor=app_color["graph_bg"],
#         )
#     ),
# ),

# # pip install pyorbital
# from pyorbital.orbital import Orbital
# satellite = Orbital('TERRA')
#
# external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
#
# app = dash.Dash(__name__, external_stylesheets=external_stylesheets)
# app.layout = html.Div(
#     html.Div([
#         html.H4('TERRA Satellite Live Feed'),
#         html.Div(id='live-update-text'),
#         dcc.Graph(id='live-update-graph'),
#         dcc.Interval(
#             id='interval-component',
#             interval=1*1000, # in milliseconds
#             n_intervals=0
#         )
#     ])
# )
#
#
# @app.callback(Output('live-update-text', 'children'),
#               Input('interval-component', 'n_intervals'))
# def update_metrics(n):
#     lon, lat, alt = satellite.get_lonlatalt(datetime.datetime.now())
#     style = {'padding': '5px', 'fontSize': '16px'}
#     return [
#         html.Span('Longitude: {0:.2f}'.format(lon), style=style),
#         html.Span('Latitude: {0:.2f}'.format(lat), style=style),
#         html.Span('Altitude: {0:0.2f}'.format(alt), style=style)
#     ]
#
#
# # Multiple components can update everytime interval gets fired.
# @app.callback(Output('live-update-graph', 'figure'),
#               Input('interval-component', 'n_intervals'))
# def update_graph_live(n):
#     satellite = Orbital('TERRA')
#     data = {
#         'time': [],
#         'Latitude': [],
#         'Longitude': [],
#         'Altitude': []
#     }
#
#     # Collect some data
#     for i in range(180):
#         time = datetime.datetime.now() - datetime.timedelta(seconds=i*20)
#         lon, lat, alt = satellite.get_lonlatalt(
#             time
#         )
#         data['Longitude'].append(lon)
#         data['Latitude'].append(lat)
#         data['Altitude'].append(alt)
#         data['time'].append(time)
#
#     # Create the graph with subplots
#     fig = plotly.tools.make_subplots(rows=2, cols=1, vertical_spacing=0.2)
#     fig['layout']['margin'] = {
#         'l': 30, 'r': 10, 'b': 30, 't': 10
#     }
#     fig['layout']['legend'] = {'x': 0, 'y': 1, 'xanchor': 'left'}
#
#     fig.append_trace({
#         'x': data['time'],
#         'y': data['Altitude'],
#         'name': 'Altitude',
#         'mode': 'lines+markers',
#         'type': 'scatter'
#     }, 1, 1)
#     fig.append_trace({
#         'x': data['Longitude'],
#         'y': data['Latitude'],
#         'text': data['time'],
#         'name': 'Longitude vs Latitude',
#         'mode': 'lines+markers',
#         'type': 'scatter'
#     }, 2, 1)
#
#     return fig
