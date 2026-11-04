%% Compare fans: operating airflow and estimated hA
% Add fans in the INPUTS section. Everything below updates automatically.
% Q = airflow in CFM. P = static pressure in Pa.
% Use the full curve, with Q increasing from zero to the free-air endpoint.

%% INPUTS
fans = struct([]);  % Start a fresh list each time the script runs.

% Fan 1: approximate points read from the Huazhun full-speed graph.
fans(1).name = 'Huazhun BO4010N0 36.6W (24 V, 130g)';
fans(1).Q = [0 10 20 25 30 35 40 50 60 70 79.1];
fans(1).P = [7.30 6.12 4.93 4.57 3.96 3.45 3.10 2.66 2.03 1.04 0] ...
            * 249.089;  % Convert inH2O to Pa.

% Fan 2: approximate points read from the Sanyo full-speed graph.
fans(2).name = 'Sanyo 9HVA0612P1J001 33.6W (12 V, 130g)';
fans(2).Q = [0 0.5 0.75 1 1.1 1.25 1.5 1.75 2 2.39] * 35.3147;
fans(2).P = [2000 1600 1360 1100 1020 960 880 780 520 0];
% The Q values above are converted from m^3/min to CFM.

% Sanyo 9GV0624P1G03 — nominal 24 V, 100% PWM
% Published rated input: 33.6 W
% Approximate digitized points; no voltage or RPM scaling.

fans(3).name = 'Sanyo 9GV0624P1G03 33.6W (24 V, 130g)';

fans(3).Q = [0 0.2 0.4 0.6 0.8 1.0 1.2 ...
             1.4 1.6 1.8 2.0 2.2 2.37] * 35.3147; % CFM

fans(3).P = [751 670 590 515 440 365 354 ...
             357 348 305 215 110 0];               % Pa

% Approximate points read from the manufacturer's 12 V / 100% PWM graph.
fans(4).name = 'Sanyo 9TD12P6G001 12W (12 V, 90g)';

fans(4).Q = [0 0.1 0.2 0.3 0.4 0.5 0.6 ...
             0.7 0.8 0.9 1.0 1.1 1.13] * 35.3147; % CFM

fans(4).P = [560 550 530 505 470 425 380 ...
             320 250 180 100 25 0];               % Pa

% SilverStone at 6.5 W — estimated curve at 10,412 RPM
fans(5).name = 'SilverStone 6.5 W (12V, 110g)';

fans(5).Q = [0 4.5812 11.4529 18.6024 25.4047 ...
             27.1400 27.9729 31.0965 39.2871 45.6729]; % CFM

fans(5).P = [300.03 240.02 205.53 166.79 152.61 ...
             149.30 147.41 134.66 71.82 0];            % Pa


% SilverStone full speed — assumed 15,000 RPM
% Measured electrical input in test setup: 17.3 W
fans(6).name = 'SilverStone 17.3W (12V, 110g)';

fans(6).Q = [0 6.6 16.5 26.8 36.6 ...
             39.1 40.3 44.8 56.6 65.8]; % CFM

fans(6).P = [63.5 50.8 43.5 35.3 32.3 ...
             31.6 31.2 28.5 15.2 0] ...
             * 9.80665; % mmH2O to Pa

% ADD ANOTHER FAN: copy these three lines and enter your own data.
% fans(5).name = 'Another fan';
% fans(5).Q = [ ... ];  % CFM
% fans(5).P = [ ... ];  % Pa

% Unit conversions, if needed:
% inH2O * 249.089 = Pa; mmH2O * 9.80665 = Pa.
% m^3/min * 35.3147 = CFM; m^3/h / 1.69901 = CFM.

%% SYSTEM AND THERMAL REFERENCE INPUTS
systemMethod = "points";  % Choose "coefficient" or "points"
Kentered = 0.628;              % Previous K, in Pa/CFM^2

% To fit your own system curve, choose "points" above and fill both arrays.
% Each pair must describe the SAME system geometry and airflow path.
% Powers: 1.73, 3.46, 5.2, 6.9, 8.6, 10.4, 12.1, 13.8, 15.7, 17.3 W
systemQ_CFM = [10.5466 14.0622 15.4684 17.5777 18.9840 ...
               20.3902 21.0933 22.4995 22.4995 23.9057];

systemDP_Pa = [48.4105 95.9204 147.8537 183.8508 219.4411 ...
               255.0893 286.8178 311.8857 350.3934 368.7711];
% Use pressure losses consistent with the fan curve's pressure definition.
% A pressure drop across only part of the duct is not the whole system loss.

hAref = 0.145;   % Reference hA, W/K, at referencePower_W per fan
n = 0.508;      % Empirical exponent; unchanged from the previous script

referenceMethod = "fan_curve";  % Choose "fan_curve" or "flow_test"
referencePower_W = 6.5;         % Power PER FAN in the reference thermal test

% Measured points bracketing the reference power.
testPower_W = [5.2 6.9];
testRPM = [9540 10680];
testOutletVelocity_m_s = [2.2 2.5];
outletDiameter_m = 0.065;       % Circular flow-test outlet

% Original test fan's full-speed curve, NOT the candidate fans above.
% Approximate points read from the uploaded 6038 graph.
testCurveRPM = 15000;          % Assumed RPM of this full-speed curve
testCurveQ = [0 6.6 16.5 26.8 36.6 39.1 40.3 44.8 56.6 65.8]; % CFM
testCurveP = [63.5 50.8 43.5 35.3 32.3 31.6 31.2 28.5 15.2 0] ...
             * 9.80665;       % Convert mmH2O to Pa

%% CALCULATE THE SYSTEM CURVE: pressure drop = K * airflow^2
switch systemMethod
    case "coefficient"
        Ksystem = Kentered;
    case "points"
        Qdata = systemQ_CFM(:);
        Pdata = systemDP_Pa(:);
        if isempty(Qdata) || numel(Qdata) ~= numel(Pdata) || ...
                any(~isfinite(Qdata)) || any(~isfinite(Pdata)) || ...
                any(Qdata < 0) || any(Pdata < 0) || ~any(Qdata > 0)
            error('Enter matching nonnegative system Q and pressure points, including positive flow.');
        end

        % Least-squares fit through the origin, minimizing pressure error.
        Qsquared = Qdata.^2;
        Ksystem = (Qsquared' * Pdata) / (Qsquared' * Qsquared);
        if Ksystem <= 0
            error('System points must give a positive pressure-loss coefficient.');
        end
        fitRMSE_Pa = sqrt(mean((Pdata - Ksystem * Qdata.^2).^2));
        fprintf('System fit pressure RMSE = %.2f Pa\n', fitRMSE_Pa);
    otherwise
        error('Choose systemMethod = "coefficient" or "points".');
end

systemPressure = @(Q) Ksystem * Q.^2;
fprintf('System curve: pressure [Pa] = %.6g * airflow [CFM]^2\n\n', Ksystem);

%% COMPUTE BOTH REFERENCE AIRFLOWS

% Method 1: interpolate measured outlet velocity, then use Q = velocity * area.
referenceVelocity = interp1(testPower_W, testOutletVelocity_m_s, ...
    referencePower_W, 'linear');
outletArea_m2 = pi * outletDiameter_m^2 / 4;
Qref_flow_test = referenceVelocity * outletArea_m2 / 0.00047194745;

% Method 2: interpolate measured RPM and scale the original test fan curve.
referenceRPM = interp1(testPower_W, testRPM, referencePower_W, 'linear');
speedRatio = referenceRPM / testCurveRPM;
referenceCurveQ = testCurveQ * speedRatio;
referenceCurveP = testCurveP * speedRatio^2;
referenceFanPressure = @(Q) interp1(referenceCurveQ, referenceCurveP, Q, 'linear');
Qref_fan_curve = fzero(@(Q) referenceFanPressure(Q) - systemPressure(Q), ...
    [0 referenceCurveQ(end)]);

% Select the reference airflow used in all candidate hA calculations.
switch referenceMethod
    case "flow_test"
        Qref = Qref_flow_test;
    case "fan_curve"
        Qref = Qref_fan_curve;
    otherwise
        error('Choose referenceMethod = "flow_test" or "fan_curve".');
end

referenceMethods = ["flow_test"; "fan_curve"];
referenceFlows = [Qref_flow_test; Qref_fan_curve];
referenceSelected = referenceMethods == referenceMethod;
referenceComparison = table(referenceMethods, referenceFlows, referenceSelected, ...
    'VariableNames', {'Reference_method', 'Flow_CFM', 'Selected'});
disp(referenceComparison);
fprintf('Using %s: Qref = %.2f CFM at %.2f W per fan\n', ...
    char(referenceMethod), Qref, referencePower_W);
fprintf('hAref = %.3f W/K; n = %.3f\n\n', hAref, n);

%% CALCULATE EACH FAN'S OPERATING POINT
numFans = numel(fans);
fanNames = strings(numFans, 1);
Qop = zeros(numFans, 1);
Pop = zeros(numFans, 1);
hA = zeros(numFans, 1);

for i = 1:numFans
    Q = fans(i).Q;
    P = fans(i).P;
    fanNames(i) = string(fans(i).name);

    fanPressure = @(q) interp1(Q, P, q, 'linear');
    difference = @(q) fanPressure(q) - systemPressure(q);

    Qop(i) = fzero(difference, [0 Q(end)]);
    Pop(i) = systemPressure(Qop(i));
    hA(i) = hAref * (Qop(i) / Qref)^n;
end

hA_gain_percent = 100 * (hA / hAref - 1);

%% COMPARISON TABLE
results = table(fanNames, Qop, Pop, hA, hA_gain_percent, ...
    'VariableNames', {'Fan', 'Flow_CFM', 'Pressure_Pa', ...
                      'hA_W_per_K', 'hA_gain_percent'});
disp(results);

%% ONE GRAPH WITH ALL FANS AND THE SYSTEM CURVE
colors = lines(numFans);
maxFlow = max(arrayfun(@(f) max(f.Q), fans));
maxPressure = max(arrayfun(@(f) max(f.P), fans));
Qplot = linspace(0, maxFlow, 500);

figure('Name', 'All fans');
plot(Qplot, systemPressure(Qplot), 'k--', 'LineWidth', 2, ...
    'DisplayName', 'System curve');
hold on;

if systemMethod == "points"
    plot(systemQ_CFM, systemDP_Pa, 'ks', 'MarkerFaceColor', 'w', ...
        'MarkerSize', 7, 'DisplayName', 'System input points');
end

for i = 1:numFans
    Qplot = linspace(0, max(fans(i).Q), 500);
    Pplot = interp1(fans(i).Q, fans(i).P, Qplot, 'linear');

    plot(Qplot, Pplot, 'Color', colors(i,:), 'LineWidth', 2, ...
        'DisplayName', fans(i).name);

    plot(Qop(i), Pop(i), 'o', 'Color', colors(i,:), ...
        'MarkerFaceColor', colors(i,:), 'MarkerSize', 8, ...
        'HandleVisibility', 'off');

    text(Qop(i), Pop(i), sprintf('  %.1f CFM', Qop(i)), ...
        'Color', colors(i,:), 'VerticalAlignment', 'bottom');
end

grid on;
xlabel('Airflow (CFM)');
ylabel('Pressure (Pa)');
title('Fan curves and operating points');
legend('Location', 'best', 'Interpreter', 'none');
xlim([0 maxFlow]);
ylim([0 1.15 * maxPressure]);

%% SEPARATE GRAPH OF THE SYSTEM FIT
if systemMethod == "points"
    QsystemPlot = linspace(0, max(systemQ_CFM), 300);
    figure('Name', 'System curve fit');
    plot(QsystemPlot, systemPressure(QsystemPlot), 'k-', 'LineWidth', 2);
    hold on;
    plot(systemQ_CFM, systemDP_Pa, 'ks', 'MarkerFaceColor', 'w', ...
        'MarkerSize', 7);
    grid on;
    xlabel('Airflow (CFM)');
    ylabel('Pressure drop (Pa)');
    title(sprintf('System fit: pressure = %.4g * airflow^2', Ksystem));
    legend('Quadratic fit through origin', 'System input points', ...
        'Location', 'best');
end

%% SEPARATE GRAPH FOR EACH FAN: INPUT POINTS AND INTERPOLATED CURVE
for i = 1:numFans
    Qplot = linspace(0, max(fans(i).Q), 500);
    Pplot = interp1(fans(i).Q, fans(i).P, Qplot, 'linear');

    figure('Name', fans(i).name);
    plot(Qplot, Pplot, '-', 'Color', colors(i,:), 'LineWidth', 2);
    hold on;
    plot(fans(i).Q, fans(i).P, 'ko', 'MarkerFaceColor', 'w', ...
        'MarkerSize', 7);

    grid on;
    xlabel('Airflow (CFM)');
    ylabel('Pressure (Pa)');
    title(fans(i).name, 'Interpreter', 'none');
    legend('Interpolated curve', 'Input vector points', 'Location', 'best');
end

% These fans are compared individually, not combined in series or parallel.
% hA assumes unchanged cooling geometry and airflow distribution.
% Candidate fan curves are used as entered; only the test reference is RPM-scaled.
% No electrical-power prediction is performed.
% The flow-test method assumes representative average velocity at the 65 mm outlet.
% Keep the reference geometry consistent with the thermal test.
% Inspect the plot if a fan curve crosses the system curve more than once.