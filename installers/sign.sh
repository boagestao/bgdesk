CURR_DIR=$(dirname $0)
cd $CURR_DIR

input_file=$1
if [ ! -f "$input_file" ]
then
    echo 'First argument must be path to binary'
    echo $input_file
    exit 1
fi

# Check that input file is a windows PE (Portable Executable)
if ! ( file "$input_file" | grep -q PE )
then
    echo 'File must be a Portable Executable (PE) file.'
    exit 0
fi

# Check that osslsigncode is installed
if ! command -v osslsigncode >/dev/null 2>&1 ; then
    echo "osslsigncode utility is not present or missing from PATH. Binary cannot be signed."
    exit 1
fi

orig_file="${input_file}_unsigned"

mv "$input_file" "$orig_file"

osslsigncode sign -certs "../config/certs/sign.crt" -key "../config/certs/sign.key" -n "BGDesk" -i "https://boagestao.com.br/bgdesk/" -t "http://timestamp.comodoca.com/authenticode" -in "$orig_file" -out "$input_file"

rm "$orig_file"