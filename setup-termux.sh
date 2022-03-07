#!/bin/bash

declare -r minPy=8 maxPy=9
declare -r repo="https://github.com/usergeteam/loader"
declare -r -A pyLinks=(
    [aarch64]="https://github.com/Termux-pod/termux-pod/blob/main/aarch64/python/python-3.9.7/python_3.9.7_aarch64.deb?raw=true"
    [arm]="https://github.com/Termux-pod/termux-pod/blob/main/arm/python/python-3.9.7/python_3.9.7_arm.deb?raw=true"
    [i686]="https://github.com/Termux-pod/termux-pod/blob/main/i686/python/python-3.9.7/python_3.9.7_i686.deb?raw=true"
    [x86_64]="https://github.com/Termux-pod/termux-pod/tree/main/x86_64/python/python-3.8.6?raw=true"
)

log() {
    test -n "$@" && printf "\e[36mINFO:\e[0m %b\n" "$@"
}

die() {
    test -n "$@" && printf "\e[31mERROR:\e[0m %b\n" "$@"
    exit 1
}

_checkTermux() {
    log "Checking Termux..."
    test -n "$(termux-info 2> /dev/null)" \
        || die "This script is only for termux users!" 
}

_checkRequirement() {
    test -n $1 && {
        log "Checking Requirement: $1"
        test -n "$(command $1 --help 2> /dev/null)" \
            || die "The program $1 is not installed, Install it by executing:\n pkg install $1 -y"
    }
}

_getPythonVersion() {
    ptn='s|Python (3\.[0-9]{1,2}\.[0-9]{1,2}).*|\1|g'
    echo $(sed -E "$ptn" <<< "$(python3 -V 2> /dev/null)")
}

_getDeviceArchitecture() {
    echo "$(uname -m)"
}

_uninstallPython() {
    log "Uninstalling Python due to verison not match..."
    test "$(pkg uninstall python -y 2> /dev/null)" \
        || die "Couldn't uninstall Python, Uninstall manually and run this script again."
    
}

_installPythonFromPath() {
    log "Now Installing..."
    test "$(dpkg -i $1 2> /dev/null)" || die "Couldn't install Python"
    log "Installed Python version: $(_getPythonVersion)"
    $(rm -rf $path)
}

_downloadPython() {
    local path v out
    log "Downloading Required Python verison..."
    path=$(echo $1 | sed -e "s|.*\/||g" -e "s|\?.*||")
    test -d $path && {
        _installPythonFromPath "$path"
        return
    }
    out=$(wget -O $path $1 &> /dev/null)
    if test -z $out; then
        log "Downloaded $path"
        _installPythonFromPath "$path"
    else
        die "Couldn't Download Python"
    fi
}

_installPython() {
    local arc
    _checkRequirement "wget"
    arc=$(_getDeviceArchitecture)
    test $arc || die "Couldn't find CPU Architecture!"
    test -n "${pyLinks[$arc]}" \
        && _downloadPython "${pyLinks[$arc]}" \
        || die "Couldn't find any suitable python version for CPU Architecture: $arc"
}

_reinstallPython() {
    _uninstallPython
    _installPython
}

_checkPython() {
    local ptn v pyv
    pyv=$(_getPythonVersion)
    if test -n "$pyv"; then
        v=$(sed -E 's|3\.(.*)\.[0-9]{1,2}|\1|g' <<< $pyv)
        if test $v -lt $minPy; then
            log "minimum python version required: 3.${minPy}, current: $pyv"
            _reinstallPython
        elif test $v -gt $maxPy; then
            log "maximum python version required: 3.${maxPy}, current: $pyv"
            _reinstallPython
        else
            log "Found Installed Python version: $pyv"
        fi
    else
        log "Python not found!"
        _installPython
    fi
}

_setupLoader() {
    local out
    log "Cloning into 'loader'..."
    _checkRequirement "git"
    test -d "loader" && $(rm -rf loader)
    out=$(git clone $repo 2> /dev/null)
    test -z "$out" && {
        $(mv loader/config.env.sample loader/config.env)
        log "Loader is set up successfully..."
        log "Now fill config.env file by executing:\n\tcd loader && nano config.env"
        log "start userge by executing:\n\tbash install_req && bash run"
    }
}

main() {
    _checkTermux
    _checkPython
    _setupLoader
}

main
