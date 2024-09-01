from sympy import false
from waveware.post_processing import *
df_sum = load_summary()

run_id = 200

out = process_run(df_sum,run_id,plot=True)

locals().update(**out) #monkeypatch here

#Constraints
Cntl = ['u']
Target = ["z1","v1","z2","v2"]
Txdot = ["v1","a1","v2","a2"]
#Target = ["z1","v1"]
#Txdot = ['v1','a1']

#XX = np.stack((z1,v1,z2,v2),axis=-1)
XX = np.stack((out.get(k) for k in Target),axis=-1)
XD = np.stack((out.get(k) for k in Txdot ),axis=-1)
#time = tm.to_numpy()

x_train = {'x':XX}#,'x_dot':XD}

#diff = ps.FiniteDifference(order=2)
diff = ps.SINDyDerivative(kind="kalman", alpha=0.05)
poly_bias = ps.PolynomialLibrary(degree=2, include_bias=True)
poly_only = ps.PolynomialLibrary(degree=1, include_bias=False)
ident_lib = ps.IdentityLibrary()

exp_functions = [lambda x : np.e**(-np.abs(x)),
                 lambda x: np.e**(x),
                 lambda x: np.e**(-x)]
exp_fnc_names = [lambda x: f'e^(-|{x}|)',lambda x: f'e^({x})',lambda x: f'e^(-{x})']
trig_functions = [lambda x: np.real(np.e**(1j*x)),lambda x: np.real(np.e**(1j*-x))]
trig_fnc_names = [lambda x: f'e^(i*{x})',lambda x: f'e^(-i*{x})']
diff_func = [lambda x,y: x-y,lambda x,y: x/(1+np.abs(y))]
diff_fnc_names = [lambda x,y: f'{x}-{y}',lambda x,y: f'{x}/(1+|{y}|)']
exp_lib = ps.CustomLibrary(library_functions=exp_functions,
                           function_names=exp_fnc_names)
trig_lib = ps.CustomLibrary(library_functions=trig_functions,
                            function_names=trig_fnc_names)
diff_lib = ps.CustomLibrary(library_functions=diff_func,
                            function_names=diff_fnc_names)

tensor_mtx = [[1,1,0],
              [1,0,1],
              [0,1,1],]

cmpx_lib = ps.GeneralizedLibrary([exp_lib,trig_lib,diff_lib],
                                tensor_array=tensor_mtx)



feat_lib = poly_bias*cmpx_lib
#feat_lib = poly_only*
#feat_lib = poly

PARM_V = Target+Cntl
feat_lib.fit(np.arange(len(PARM_V)))
finx = feat_lib.get_feature_names(PARM_V)
Nt = XX.shape[-1]
#Nt = len(Target)

ConNames = [tv.upper()+'_'+fv for tv in Target for fv in finx if tv not in Cntl]

Cmtx = {}
Ckzero = {}

ztol = 0.5

ineq_type = True
force_vel_neg = True

cinx = 0
for i,cn in enumerate(ConNames):
    if cn.startswith('Z1'):
        #apply rate limits
        if cn.endswith('_v1'):
            Cmtx[(cinx,i)] = 1
            Ckzero[cinx] = 1 + (ztol if ineq_type else 0)
            if ineq_type:
                Cmtx[(cinx+1,i)] = -1
                Ckzero[cinx+1] = 1-ztol
        else:
            Cmtx[(cinx,i)] = 1
            Ckzero[cinx] = 0 + (ztol if ineq_type else 0)
            if ineq_type:
                Cmtx[(cinx+1,i)] = -1
                Ckzero[cinx+1] = ztol      
        cinx += 1 if not ineq_type else 2

    elif cn.startswith('Z2'):
        #apply rate limits
        if cn.endswith('_v2'):
            Cmtx[(cinx,i)] = 1
            Ckzero[cinx] = 1 + (ztol if ineq_type else 0)
            if ineq_type:
                Cmtx[(cinx+1,i)] = -1
                Ckzero[cinx+1] = 1-ztol
        else:
            Cmtx[(cinx,i)] = 1
            Ckzero[cinx] = 0 + (ztol if ineq_type else 0)
            if ineq_type:
                Cmtx[(cinx+1,i)] = -1
                Ckzero[cinx+1] = ztol
        cinx += 1 if not ineq_type else 2

#     elif cn.startswith('V1') and ineq_type and force_vel_neg:
#         #ensure velocity contrib is less than 0
#         if cn.endswith('_v1'):
#             Cmtx[(cinx,i)] = -1
#             Ckzero[cinx] = 0
#             cinx += 1
# 
#     elif cn.startswith('V2') and ineq_type and force_vel_neg:
#         #ensure velocity contrib is less than 0
#         if cn.endswith('_v2'):
#             Cmtx[(cinx,i)] = -1
#             Ckzero[cinx] = 0
#             cinx += 1    

Nc = len(Ckzero)

Cz = np.zeros(Nc)
for k,v in Ckzero.items():
    Cz[k] = v
    
Cm = np.zeros((Nc,len(finx)*Nt))
for k,v in Cmtx.items():
    Cm[k[0],k[1]] = v

def plot_constraints():
    figure()
    title('constraints')
    imshow(Cm)
    grid()
    yticks(np.arange(len(Ckzero))-0.5,labels=[])
    xticks(np.arange(len(ConNames))-0.5,labels=ConNames,rotation=90)
    colorbar()

optimizer = ps.STLSQ(threshold=0.1,max_iter=100)
# optimizer = ps.ConstrainedSR3(threshold=0.1,max_iter=100,constraint_lhs=Cm,constraint_rhs=Cz,constraint_order='target',inequality_constraints=ineq_type,thresholder='l1')
#optimizer = ps.StableLinearSR3(threshold=1,max_iter=100,constraint_lhs=Cm,constraint_rhs=Cz,constraint_order='target',inequality_constraints=ineq_type,thresholder='l2')
#optimizer = ps.StableLinearSR3(threshold=0.1,max_iter=100)

sindy_cnfg = dict(
        differentiation_method=diff,
        feature_library=feat_lib,
        optimizer=optimizer,
        feature_names=PARM_V,
    )

U = xf.reshape(len(xf),1)

model = ps.SINDy(**sindy_cnfg)

kwrun ={'t':time,'u':U}

model.fit(**x_train,**kwrun)

#print(model.print())
scr = model.score(**x_train,**kwrun)
print(f't: {toff} | scr: {scr}')
print(model.print())

print(model.score(**x_train,**kwrun))


def simulate():
    sim = model.simulate([0,0,0,0],time,U)
    return sim