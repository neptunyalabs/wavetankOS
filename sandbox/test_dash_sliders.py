import dash
import dash_core_components as dcc
from dash import html

app = dash.Dash(__name__)

app.layout = html.Div([
        html.H6("INPUT:",className="graph__title"),
        html.Div([
            html.Div([
                html.Div([
                        dcc.Slider(
                            id='mhd_window_slider',
                            min=0.05,
                            max=1.4,
                            step=0.005,
                            value=0.5,
                            vertical=True,
                        ), 
                        html.H1(children='S1'),
                    ], style={ 'width':'50px', 'height':'500px',"display": "table-cell" }),
                html.Div([
                        dcc.Slider(
                            id='mhd_window_slider',
                            min=0.05,
                            max=1.4,
                            step=0.005,
                            value=0.5,
                            vertical=True,
                        ), 
                        html.H1(children='S1'),
                    ], style={ 'width':'50px',"display": "table-cell" ,'height':'500px' }),                                        
                    ],
                style={
                "display": "table-row",
                "width": "inherit",
                })
            ],
            style={
                "display": "table",
                "width": "25%",
                "height": "25%",
            },
            className="graph__container first",
        ),
])


# app.layout = html.Div(children=[
#     html.H1(children='Vertical Slider has stopped working.'),
#     html.Div([
#         dcc.Slider(
#             id='mhd_window_slider',
#             min=0.05,
#             max=1.4,
#             step=0.005,
#             value=0.5,
#             vertical=True,
#         ),
#     ], style={ 'width':'50px', 'height':'500px' }),
#     
#     html.H1(children='Vertical RangeSlider still works.'),
#     html.Div([
#         dcc.RangeSlider(
#             id='mhd_clim_slider',
#             count=1,
#             min=0,
#             max=3,
#             step=0.01,
#             value=[0.02, 1],
#             vertical=True,
#         )
#     ], style={ 'width':'50px', 'height':'500px' }),
# ])

if __name__ == '__main__':
    app.run_server(debug=True)