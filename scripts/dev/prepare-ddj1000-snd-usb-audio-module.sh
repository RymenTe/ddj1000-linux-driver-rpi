#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/../.." && pwd)"

kernel_version="$(uname -r)"
source_package="linux-hwe-6.17"
work_dir="/tmp/ddj1000-linux-driver-kernel-src"
apt_dir="/tmp/ddj1000-linux-driver-apt"
build_dir="$repo_dir/build/ddj1000-driver"
patch_file="$repo_dir/patches/linux/snd-usb-audio-ddj1000-composite-quirk.patch"
key_file="$build_dir/ddj1000-linux-driver-mok.key"
der_file="$build_dir/ddj1000-linux-driver-mok.der"
module_name="snd-usb-audio-ddj1000.ko"
midi_module_name="snd-usbmidi-lib-test.ko"
platform="auto"
source_dir=""
stable_git_url="${DDJ1000_STABLE_GIT_URL:-https://github.com/gregkh/linux}"

usage() {
    cat <<EOF
Usage: $0 [--kernel-version VERSION] [--platform auto|rpi|ubuntu]
          [--source-package NAME] [--source-dir PATH]

ubuntu: downloads Ubuntu kernel source into /tmp, applies the DDJ-1000
        snd-usb-audio quirk patch, builds the USB audio modules against the
        installed kernel headers and signs them with a local MOK key.
        This does not enroll the MOK key. With Secure Boot enabled, run the
        printed mokutil command manually, reboot, and enroll the key.

rpi:    Raspberry Pi OS (Pi 4 / Pi 5, 64-bit). Takes sound/usb either from
        --source-dir (e.g. ~/rpi-linux checked out at your running kernel) or
        from the matching upstream stable tag (v<X.Y.Z> of \$(uname -r)),
        applies the matching patch from patches/linux/rpi/ and
        builds against /lib/modules/\$(uname -r)/build. No signing needed.

auto (default) picks rpi on Raspberry Pi hardware or rpt/rpi kernels.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kernel-version)
            kernel_version="$2"
            shift 2
            ;;
        --source-package)
            source_package="$2"
            shift 2
            ;;
        --platform)
            platform="$2"
            shift 2
            ;;
        --source-dir)
            source_dir="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

is_raspberry_pi() {
    if [[ -r /proc/device-tree/model ]] && tr -d '\0' < /proc/device-tree/model | grep -q "Raspberry Pi"; then
        return 0
    fi
    [[ "$kernel_version" == *rpt* || "$kernel_version" == *rpi* ]]
}

if [[ "$platform" == "auto" ]]; then
    if is_raspberry_pi; then platform="rpi"; else platform="ubuntu"; fi
fi

if [[ ! -d "/lib/modules/$kernel_version/build" ]]; then
    echo "Missing kernel headers: /lib/modules/$kernel_version/build" >&2
    if [[ "$platform" == "rpi" ]]; then
        echo "On Raspberry Pi OS install them with:" >&2
        echo "  sudo apt install linux-headers-$kernel_version" >&2
    fi
    exit 1
fi

prepare_rpi() {
    local upstream_version series rpi_patch tree src_root head_version
    upstream_version="${kernel_version%%[+-]*}"
    series="$(cut -d. -f1-2 <<< "$upstream_version")"
    rpi_patch="$repo_dir/patches/linux/rpi/snd-usb-audio-ddj1000-rpi-$series.patch"
    tree="$work_dir/rpi-tree"

    if [[ ! -f "$rpi_patch" ]]; then
        echo "No Raspberry Pi patch for kernel series $series: $rpi_patch" >&2
        echo "Available:" >&2
        ls "$repo_dir/patches/linux/rpi/" >&2 || true
        exit 1
    fi

    if [[ -n "$source_dir" ]]; then
        src_root="$(cd -- "$source_dir" && pwd)"
        if [[ -f "$src_root/Makefile" ]]; then
            head_version="$(awk '/^VERSION =/{v=$3} /^PATCHLEVEL =/{p=$3} /^SUBLEVEL =/{s=$3} END{print v"."p"."s}' "$src_root/Makefile")"
            if [[ "$head_version" != "$upstream_version" ]]; then
                echo "[WARN] $src_root is $head_version, running kernel is $upstream_version." >&2
                echo "[WARN] Out-of-tree sound/usb from another sublevel may fail to load (unknown symbols)." >&2
            fi
        fi
    else
        src_root="$work_dir/linux-v$upstream_version"
        if [[ ! -f "$src_root/sound/usb/quirks-table.h" ]]; then
            rm -rf "$src_root"
            echo "Fetching sound/usb from $stable_git_url tag v$upstream_version..."
            git clone --quiet --depth 1 --filter=blob:none --sparse \
                --branch "v$upstream_version" "$stable_git_url" "$src_root"
            git -C "$src_root" sparse-checkout set sound/usb
        fi
    fi

    if [[ ! -f "$src_root/sound/usb/quirks-table.h" ]]; then
        echo "No sound/usb/quirks-table.h under $src_root" >&2
        exit 1
    fi

    # Always build from a pristine copy so a source tree that was patched by
    # hand earlier (old quirk without the endpoint fix) is never mixed in.
    rm -rf "$tree"
    mkdir -p "$tree/sound"
    cp -a "$src_root/sound/usb" "$tree/sound/usb"
    find "$tree/sound/usb" \( -name '*.o' -o -name '*.ko' -o -name '*.mod*' -o -name '.*.cmd' \) -delete

    if grep -q "0x2b73, 0x0020" "$tree/sound/usb/quirks-table.h"; then
        echo "$src_root already contains a DDJ-1000 quirk." >&2
        echo "Use a clean tree, e.g.: git -C $src_root checkout -- sound/usb" >&2
        exit 1
    fi

    echo "Applying $(basename "$rpi_patch")..."
    patch --batch --forward -p1 -d "$tree" < "$rpi_patch"

    echo "Building sound/usb modules against $kernel_version headers..."
    make -C "/lib/modules/$kernel_version/build" M="$tree/sound/usb" -j"$(nproc)" modules

    cp "$tree/sound/usb/snd-usb-audio.ko" "$build_dir/$module_name"
    cp "$tree/sound/usb/snd-usbmidi-lib.ko" "$build_dir/$midi_module_name"

    cat <<EOF2

Built for $kernel_version:
  $build_dir/$module_name
  $build_dir/$midi_module_name

Raspberry Pi has no Secure Boot module signing, nothing to enroll.

Test-load:  bash scripts/dev/load-ddj1000-snd-usb-audio-test-module.sh
Install:    bash scripts/install-ddj1000-audio-driver.sh install
EOF2
}

mkdir -p "$build_dir"
if [[ "$platform" == "rpi" ]]; then
    mkdir -p "$work_dir"
    prepare_rpi
    exit 0
fi

mkdir -p "$apt_dir/lists/partial" "$apt_dir/cache/archives/partial" "$work_dir" "$build_dir"

cat > "$apt_dir/ubuntu-src.sources" <<'EOF'
Types: deb-src
URIs: http://de.archive.ubuntu.com/ubuntu/
Suites: noble noble-updates noble-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb-src
URIs: http://security.ubuntu.com/ubuntu/
Suites: noble-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF

apt_opts=(
    -o "Dir::Etc::sourceparts=$apt_dir"
    -o "Dir::Etc::sourcelist=/dev/null"
    -o "Dir::State::lists=$apt_dir/lists"
    -o "Dir::Cache=$apt_dir/cache"
    -o "APT::Get::List-Cleanup=0"
)

echo "Updating temporary deb-src lists..."
apt-get "${apt_opts[@]}" update

echo "Downloading $source_package source into $work_dir..."
(
    cd "$work_dir"
    apt-get "${apt_opts[@]}" source --download-only "$source_package"
)

dsc_file="$(find "$work_dir" -maxdepth 1 -name "${source_package}_*.dsc" | sort -V | tail -n 1)"
if [[ -z "$dsc_file" ]]; then
    echo "No .dsc downloaded for $source_package" >&2
    exit 1
fi

source_dir="$(find "$work_dir" -maxdepth 1 -type d -name "${source_package}-*" | sort -V | tail -n 1)"
if [[ -n "$source_dir" ]]; then
    echo "Removing stale extracted source tree $source_dir..."
    rm -rf "$source_dir"
fi

echo "Extracting $dsc_file..."
(
    cd "$work_dir"
    dpkg-source -x "$dsc_file"
)
source_dir="$(find "$work_dir" -maxdepth 1 -type d -name "${source_package}-*" | sort -V | tail -n 1)"

if [[ -z "$source_dir" || ! -f "$source_dir/sound/usb/quirks-table.h" ]]; then
    echo "Could not locate extracted kernel source with sound/usb/quirks-table.h" >&2
    exit 1
fi

if ! grep -q "0x2b73, 0x0020" "$source_dir/sound/usb/quirks-table.h"; then
    echo "Applying DDJ-1000 quirk patch..."
    patch --batch --forward -d "$source_dir" -p0 < "$patch_file"
else
    echo "DDJ-1000 quirk already present in source tree."
fi

echo "Building sound/usb modules against $kernel_version headers..."
make -C "/lib/modules/$kernel_version/build" M="$source_dir/sound/usb" modules

cp "$source_dir/sound/usb/snd-usb-audio.ko" "$build_dir/$module_name"
cp "$source_dir/sound/usb/snd-usbmidi-lib.ko" "$build_dir/$midi_module_name"

if [[ ! -f "$key_file" || ! -f "$der_file" ]]; then
    echo "Creating local MOK signing key under $build_dir..."
    openssl req \
        -new -x509 -newkey rsa:2048 \
        -keyout "$key_file" \
        -outform DER \
        -out "$der_file" \
        -nodes \
        -days 36500 \
        -subj "/CN=DDJ1000 Linux Driver test module signing/"
fi

sign_file="/usr/src/linux-headers-$kernel_version/scripts/sign-file"
if [[ ! -x "$sign_file" ]]; then
    echo "Missing sign-file helper: $sign_file" >&2
    exit 1
fi

echo "Signing test modules..."
"$sign_file" sha256 "$key_file" "$der_file" "$build_dir/$module_name"
"$sign_file" sha256 "$key_file" "$der_file" "$build_dir/$midi_module_name"

cat <<EOF

Built:
  $build_dir/$module_name
  $build_dir/$midi_module_name

Secure Boot MOK status:
EOF
mokutil --test-key "$der_file" || true

cat <<EOF

If Secure Boot says the key is not enrolled, enroll it manually:
  sudo mokutil --import $der_file

Then reboot. In the blue MOK Manager screen choose:
  Enroll MOK -> Continue -> Yes -> enter the password you set -> Reboot

After reboot, test-load the module with:
  bash scripts/dev/load-ddj1000-snd-usb-audio-test-module.sh
EOF