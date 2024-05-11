# from piplates import DACC

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

app = dash.Dash(
    __name__,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"}
    ],
    external_stylesheets=external_stylesheets,
)
app.title = TITLE = "WAVE TANK DASHBOARD"




# TODO: 1. Wave Measure Plot w/ act position and ultrasonic distance measurements
# TODO: 2. ref height / mode selection
# TODO: 3. pid control variables and cmd speed and feedback voltage
# TODO: 4. wave input config settings
# TODO: 5. add range limit slider for bounds



app.layout = html.Div(
    [
        # HEADER / Toolbar
        html.Div(
            [
                html.Div(
                    [
                        #html.H4(TITLE, className="app__header__title"),
                        html.Img(src='https://img1.wsimg.com/isteam/ip/3f70d281-e9f0-4171-94d1-bfd90bbedd4e/Neptunya_LogoTagline_Black_SolidColor_margin.png/:/cr=t:0%25,l:0%25,w:100%25,h:100%25/rs=h:150'),
                        html.P(
                            "This Dashboard Displays current values from the neptunya waveware system when turned on",
                            className="app__header__title--grey",
                        ),
                    ],
                    className="app__header__desc two-third column",
                ),
                html.Div(
                    [
                        html.Button(
                            "Calibrate".upper(),
                            id="calibrate-btn",
                            style=btn_header,
                        )
                    ]
                ),  
                html.Div(
                    [
                        html.Button(
                            "Zero".upper(),
                            id="zero-btn",
                            style=btn_header,
                        )
                    ]
                ),
                html.Div(
                    [
                        # html.H6(
                        #     
                        #     id="daq_msg",
                        #     style={"text-align": "center"},
                        # ),
                        daq.BooleanSwitch(label="DAC ON/OFF",on=False, id="daq_on_off"),
                    ],
                    className="column",
                ),                
                html.Div([daq.StopButton(id="stop-btn", buttonText="STOP")]),                
                html.Div(
                    [
                        daq.PowerButton(label="WAVE ON/OFF",on=False, id="motor_on_off"),
                    ],
                    className="one-third column",
                ),         
            ],
            className="app__header",
        ),
        # BODY
        html.Div([
            # READOUTS
            html.Div([
                html.Div([
                    html.H6("TEST NAME:",className="graph__title"),
                    html.Div([dcc.Input("Record Data With This Title", id="title-in", style={'width':'80%','padding-left':'1%','justify-content':'left'}),
                    html.Button("RUN",id='test-log-send',style={'background-color':'#FFFFFF','height':'40px','padding-top':'0%','padding-bottom':'5%','flex-grow': 1}) ],
                    style={'displaty':'flex'}),
                    dcc.RadioItems(
                            [mode_input_parms[k] for k in wave_drive_modes],
                            #[k for k in wave_drive_modes],
                            value=wave_drive_modes[0],
                            id='mode-select',
                            inline=True,
                            inputStyle = {'width':f'{(80)/M}%', 'padding':'0 3% 3% 0'},
                            labelStyle={'width':f'{(80)/M}%','padding':'0 3% 3% 0'},
                            style={'width':'100%','background':triton_bk,'display':'inline-block'}
                        ),
                    html.Div([
                        html.Div([
                                input_card(**wave_input_parms[k]) for k in wave_inputs if k in wave_input_parms
                                ])
                        ],
                        style={
                        "display": "table-row",
                        "width": "100%",
                        "justify-content":"center"
                        })
                    ],
                    style={
                        "display": "table",
                        "width": "100%",
                        "height": "250px",
                    },
                    className="graph__container first",
                ),

                # Write Test Log
                dcc.Tabs([
                    dcc.Tab(label='TEST LOG',children=[html.Div(
                        [
                            dcc.Textarea(id='test-log',value='',style={'width': '100%', 'height': "20%"}),
                            html.Button("record".upper(),id='test-log-send',style={'background-color':'#FFFFFF','height':'30px','padding-top':'0%','padding-bottom':'5%'})
                        ]
                    )]),
                    dcc.Tab(label='CONSOLE',children=[html.Div(
                        [
                            dcc.Textarea(id='console',value='',style={'width': '100%', 'height': "20%"}),
                        ]
                    )]),                                 
                ]),
                html.Div(
                    [
                    # Station 1
                    html.H6("Wave Gen Control:".upper(),className="graph__title"),
                    readout_card("z_cur"),
                    readout_card("z_cmd"),
                    readout_card("z_wave"),
                    readout_card("v_cur"),
                    readout_card("v_cmd"),
                    readout_card("v_wave"),                        
                    
                    html.H6("Encoder Z 1-4:".upper(),className="graph__title"),
                    readout_card("z1"),
                    readout_card("z2"),
                    readout_card("z3"),
                    readout_card("z4"),

                    html.H6("Echo Sensor Z 1-4:".upper(),className="graph__title"),
                    readout_card("e1"),
                    readout_card("e2"),
                    readout_card("e3"),
                    readout_card("e4"),
                    ]
                ),

                html.Div(
                    [
                    html.H6("Read / Edit Values:".upper(),className="edit_title",style={'display':'none'}), dash_table.DataTable(  data=[],
                                columns=[],
                                page_action='none',
                                style_table={'height': '100px', 'overflowY': 'auto','width':'90%'})
                ])               
            ],
            className=" column histogram__direction",
            style={'width':'25%'}
            ),
            # PLOTS
            html.Div(
                [
                    generate_plot("Encoder Z 1-4 (mm)".upper()),
                    generate_plot("Echo Height (mm)".upper()), #TODO: wave plot
                    generate_plot("Wave Generator (m),(m/s)".upper()),
                    #TODO: test set overview
                    
                ],
                className="two-thirds column wind__speed__container",
            ),
        ],
        className="app__content body",
    ),
    dcc.Interval(
    id=f"graph-update",
    interval=2.5*1000,
    n_intervals=0,
    ),
    dcc.Interval(
    id=f"num-raw-update",
    interval=1*500.,
    n_intervals=0,
    ),    
    html.Div(id="hidden-div", style={"display":"none"})
    ],
    className="app__container body",
)














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
            print(df)
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


def format_value(k,dat):
    if dat:
        if k in e_sensors:
            return float(Decimal(data[k]).quantize(mm_accuracy_ech))
        else:
            return float(Decimal(data[k]).quantize(mm_accuracy_enc))
    return dat


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
                data= [ format_value(k,data[k]) if k in data else 0 for k in all_sys_vars]
                return data

            raise dash.exceptions.PreventUpdate

        except Exception as e:
            log.error(f'update issue: {e}',exc_info=1)
    
    raise dash.exceptions.PreventUpdate


@app.callback(Output("daq_on_off", "label"),
              Input("daq_on_off", "on"),
              prevent_initial_call=True)
def turn_on_off_daq(on):
    log.info(f"DAQ ON: {on}.")
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
    log.info(f"MOTOR ENABLED: {on}.")
    if on:
        requests.get(f"{REMOTE_HOST}/control/enable")
        return "MOTOR ENABLED"
    else:
        requests.get(f"{REMOTE_HOST}/control/disable")
        return "MOTOR DISABLE"
    
@app.callback(Output('mode-select','value'),
              Input("stop-btn", "n_clicks"))
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
















def main():
    """runs the dash / plotly process"""
    import os

    try:
        srv_host = '0.0.0.0' if ON_RASPI else '127.0.0.1'
        app.run_server(debug=not ON_RASPI,host=srv_host)

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
