const h2 = document.querySelector('.login h2');
const p = document.querySelector('.login p');
const successParagraph = document.querySelector('.success');
const errorParagraph = document.querySelector('.error');
const details = document.querySelector('#address-list');
const formInput = document.querySelector('#street_address');
const bottomSvg = document.querySelector('.bottom');

if (successParagraph || errorParagraph) {
   h2.style.marginTop = '0%';
   p.style.marginTop = '0%';
}

const makeSpaceForAutoComplete = () => {
   if (formInput.value === '') {
      bottomSvg.style.bottom = '0'
   } else {
      bottomSvg.style.bottom = '-150px'
   }
   if (window.innerWidth < 900) {
      bottomSvg.style.bottom = '0'
   }
}

const getDetails = arr => {
   if (!arr.length) {
      bottomSvg.style.bottom = '0';
      details.innerHTML = '';
      return;
   }
   details.innerHTML = '';
   let regex = /(NW)|(SE)|(SW)|(NE)/;
   arr.forEach((el, idx) => {
       let newDiv = document.createElement('div');
       let label = el.label.split(',').reverse().join(', ').replace(regex, '');
       newDiv.innerText = label;
       newDiv.id = `choice${idx}`
       newDiv.classList.add('choice');
       details.append(newDiv)
       details.style.display = 'block'
       if (window.innerWidth > 900) {
          bottomSvg.style.bottom = '-150px'
       }
   })
}

const fillInInput = (evt) => {
   formInput.value = evt.target.innerText;
   details.style.display = 'none';
   bottomSvg.style.bottom = '0';
}

async function makeAutoComplete() {
   details.style.display = formInput.value === '' ? 'none' : 'block';
   makeSpaceForAutoComplete();
   let config = {
       params: {
           apiKey: 'wkGs3Y1XsWBHM9nmv085V2IcnO6Kez1bgRd8kYrIiw4',
           query: formInput.value
       }
   }
   let res = await axios.get('https://autocomplete.geocoder.ls.hereapi.com/6.2/suggest.json', config);
   let [...places] = res.data.suggestions
   getDetails(places);
   
}

const debounce = (func) => {
   let timer;
   return () => {
       clearTimeout(timer);
       timer = setTimeout(() => (func()),500);
   }
}

formInput.addEventListener('input', debounce(makeAutoComplete));
details.addEventListener('click', fillInInput);