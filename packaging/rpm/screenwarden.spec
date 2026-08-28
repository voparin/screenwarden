Name:           screenwarden
Version:        0.1.0
Release:        1%{?dist}
Summary:        Linux parental screen time control daemon
License:        MIT
BuildArch:      noarch
Requires:       python3 >= 3.11, python3-pip

%description
screenwarden enforces daily screen time limits for child user accounts.
Includes a local web dashboard for parent control.

%install
pip3 install screenwarden --root=%{buildroot}

%files
%{_bindir}/screenwarden
%{_bindir}/screenwarden-daemon
%{_bindir}/screenwarden-notify
