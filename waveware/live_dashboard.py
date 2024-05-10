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
                html.Div([daq.StopButton(id="reset-btn", buttonText="STOP")]),                
                html.Div(
                    [
                        html.H6(
                            "WAVE ON/OFF",
                            id="motor_msg",
                            style={"text-align": "center"},
                        ),
                        daq.PowerButton(on=False, id="motor_on_off"),
                    ],
                    className="one-third column",
                ),                
                html.Div(
                    [
                        html.H6(
                            "DAC ON/OFF",
                            id="daq_msg",
                            style={"text-align": "center"},
                        ),
                        daq.PowerButton(on=False, id="daq_on_off"),
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
                    html.H6("INPUT:",className="graph__title"),
                    html.Div([dcc.Input("Test Name", id="title-in", style={'width':'80%','padding-left':'1%','justify-content':'left'}),
                    html.Button("set input",id='test-log-send',style={'background-color':'#FFFFFF','height':'30px','padding-top':'0%','padding-bottom':'5%','flex-grow': 1}) ],
                    style={'displaty':'flex'}),
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
                        "height": "300px",
                    },
                    className="graph__container first",
                ),

                # Write Test Log
                html.Div(
                    [
                        html.H6("Test Notes:".upper(),className="graph__title"),
                        dcc.Textarea(id='test-log',value='',style={'width': '100%', 'height': 200}),
                        html.Button("record".upper(),id='test-log-send',style={'background-color':'#FFFFFF','height':'30px','padding-top':'0%','padding-bottom':'5%'})
                    ]
                ),                

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
                    html.H6("Read / Edit Values:".upper(),className="edit_title",style={'display':'none'}),                      dash_table.DataTable(  data=[],
                                columns=[],
                                page_action='none',
                                style_table={'height': '300px', 'overflowY': 'auto'})
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
                new_data = requests.get(f"http://localhost:8777/getdata?after={max_ts}")
            else:
                #no data, so ask for the full blast. yeet
                new_data = requests.get(f"http://localhost:8777/getdata")



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
            new_data = requests.get(f"http://localhost:8777/getcurrent")
            data = new_data.json()
            if data:
                data= [float(Decimal(data[k]).quantize(mm_accuracy_ech)) if k in e_sensors else float(Decimal(data[k]).quantize(mm_accuracy_enc)) for k in all_sys_vars]
                return data

            raise dash.exceptions.PreventUpdate

        except Exception as e:
            log.error(f'update issue: {e}',exc_info=1)
    
    raise dash.exceptions.PreventUpdate


@app.callback(Output("daq_msg", "children"), Input("daq_on_off", "on"))
def turn_on_off_daq(on):
    log.info(f"setting {on}.")
    if on:
        requests.get(f"http://localhost:8777/turn_on")
        return "DAC ON"
    else:
        requests.get(f"http://localhost:8777/turn_off")
        return "DAC OFF"

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
#     out = requests.get(f"http://localhost:8777/reset_labels")
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
#     resp = requests.get(f"http://localhost:8777/set_labels?title={title}&sen1-x={sen1x}&sen1-rot={sen1rot}&sen2-x={sen2x}&sen2-rot={sen2rot}&air-pla={airpla}&water-pla={waterpla}")
# 
#     out = resp.text
# 
#     return out

#TODO: add note functionality 
# @app.callback(
#     Output('outy','children'),
#     Input("calibrate-btn","n_clicks"),
#     State('outy','children'),
# )
# def calibrate(btn,msg):
#     """requests calibrate and prints the response:"""
#     # if msg:
#     #     log.info(msg)
#     #     msg = [ html.P(v) for v in msg.replace('<p>','').split('</p>') ]
#     # else:
#     #    msg = []
#     resp = requests.get('http://localhost:8777/calibrate')
# 
#     msg = html.Div([html.P(resp.text)])
# 
#     return msg

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
